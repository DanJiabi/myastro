# myastro top 设计文档

版本：1.0｜实现：`src/myastro/io/top/`（包）（textual 8.x）｜启动：`myastro top`

## 0. 面板框架抽象（顶层设计）

top 定位为长期的人机交互接口，App 与面板业务严格分层：

- **App = 通用框架**：面板切换、光标保存/恢复、下钻/返回状态机、详情渲染、
  键位路由、定时刷新。不含任何面板业务逻辑。
- **Pane = 面板契约**：子类实现 `columns() / rows() / detail(key)` 三方法
  （下钻可选实现 `drill(app, key)`；作业操作声明 `allows_job_actions`）。
- **身份寻址（全应用唯一行号出口 = `_selected_key()`）**：`detail/drill/
  selected_job` 及 refresh 的光标保持全部以条目身份（渲染行首列值）为句柄，
  行号只在"身份→新行号"的恢复查找中瞬态出现。行号作数据句柄在结构上
  已不可再现（曾因此产生"详情错位"与"storage 重排光标漂移"两个 bug）。
  前置不变量：**每面板首列唯一**（job #id / ds id / mission 名 / 源名）。
  `rows(desc)` 的方向参数仅是显示关切，不进入任何取数路径。
- **注册表**：`PANES` + `PANE_KEYS`（面板）、`SOURCES`（数据源）、`TYPES`
  （数据类型）、`URL_SOURCES`（URL 生成器，io/urls.py）——新增任何一类条目
  都是登记一行 + 纯函数，UI 零改动。
- **布局**：表格占主区（`1fr`），底部为带边框的独立**详情区**
  （`#detail`，`border: round`，标题"详情（enter 展开 / esc 关闭）"，
  max-height 14）——与表格视觉分离，所有面板共用，内容多态来自 `Pane.detail`。
- 代码结构：`io/top/` 包 = panes（面板体系）/ screens（新建模态）/
  batchscreen（批量模态）/ app（框架）。

## 1. 定位

**本地数据管理的统一观察面**——htop 之于进程表，top 之于"我的天文数据资产与获取作业"。

核心原则（继承自 design-io.md §2/§3）：

- **无常驻进程**：top 不是 daemon，打开才是观察者，关掉不留任何东西
- **无中心 poller**：实时性靠 top 自己直读 aria2 RPC，持久性靠 astro.db，两路数据在渲染层合并，不养转发进程
- **观察异构执行基座**：python 执行器（寄生各调用方进程）+ aria2 daemon，top 不关心 job 由谁执行，只看 jobs 表和 RPC
- **交互克制，但含下单**：单键操作为主（r/x/s/f/n/enter/esc）。历史上
  "提交不走 TUI"是初始原则，后因删除功能的测试闭环需要可丢弃的试验品而
  反转（2026-10 讨论定案）：`n` 新建下载限定为 URL 可构造源（urls.py 注册表
  驱动的派生表单），查询型源（tess/gaia 等）仍只走 Python API——TUI 不做
  网络检索的边界不变

## 2. 信息架构：三浏览面板 + 资产下钻，按视角分工

| 面板 | 视角 | 职能 |
|---|---|---|
| `0` info | 能力 | 源注册表：状态/示例（执行器列已隐身，E1） |
| `1` jobs | 进程 | 作业视图：`f` 过滤、产出列（文件名/总体积/✓✗）、批次列 |
| `2` storage | 物理 | mission 聚合 → enter 下钻资产视图（含 source/文件名列） |

> data（时间线）面板 2026-10 裁撤（与 jobs 产出列重叠，使用频率裁决）；
> AssetsPane 保留服务下钻。另有两个模态：新建下载 `F1`（描述符驱动表单）
> 与批量下单 `F12`（索引浏览 + 多选 + ✓/☁，见 batchscreen.py）。
>
> **表单字段一律带左侧标签**（`Horizontal(Label, Input)`，标签列宽 20）：
> placeholder 只放示例（`例：…`），必填字段标 `*`，模态顶部说明 `* = 必填`；
> **带本地索引的字段标 `（索引）`**（输入前即可看出哪些字段能补全/看候选），
> 未输入时预览区给一行用法说明。
> 早期只有 placeholder 兼作字段名，一旦填写（或 F2 预填充/填示例让值非空）
> 就看不出字段含义。标签不可聚焦，不影响 Tab 环。
>
> **索引字段的提示要自解释**（用户反馈"→ 好像没作用"的教训）：
> 预览区对每个索引字段给一行状态——可补全时 `0001m0 → 0001m002（→ 接受）`；
> 输入本身已是合法键时 `field 67 = 有效值，同前缀另有 10 个（无需补全…）`；
> 无匹配、索引未构建各有明确文案。**编号型键（field 号）输入即有效，
> 补全对它们本就没有意义**——把这点说出来，比改输入语义更安全。
>
> **补全用框架能力**：索引字段挂 `Input(suggester=IndexSuggester(...))`——
> 输入即出现幽灵文本，**→ 接受**；Tab 不做自定义绑定，交还框架默认
> （焦点流转）。早期版本用自造 Tab 补全，把 Tab 的流转职责吞掉，
> 导致 legacy/ztf/ztf-meta 对话框焦点卡在索引字段上（已修）。
>
> **预填充新建 `F2`**（jobs 面板）：用选中作业的 spec 预填源与参数。
> 映射是 `build_spec` 的逆（`descriptors.prefill_from_spec`），挂在描述符层——
> 命中注册源→填参数；未命中但有 url→按自定义 URL 填；都不行→退化为空白
> 表单并提示原因。门面同一能力以 `ma.prefill(job_id)` 暴露给 CLI/第三方。

按键 `0`–`2` 切换（源/作业/存储；切面板清空 detail）；其余键位见 §3 交互规格。

渲染机制：同一张 DataTable 复用；**按需重建 + 同步恢复滚动**（实测驱动）：

- **内容签名短路**：行内容/列/面板/排序/过滤都没变 → 直接返回，不碰表格。
  否则 `clear()` + 重建会让 Textual 重绘整个部件区域——实测内容一字未改
  也每 tick 写 ~3.4KB 到终端。
- **同步恢复滚动**：`clear()` 会把滚动位置归零，而 `move_cursor` 的滚动
  要等下一次布局才生效 → 中间多出一帧"列表顶部"。实测：光标在视口外时
  1 次刷新产生 **2 帧**（scroll 0 → 58），每 2 秒跳顶一次＝**闪屏**；
  光标在视口内时只有 1 帧（滚动本来就是 0），所以"闪不闪"取决于选中项
  是否在可视范围内。重建后用 `scroll_to(y=saved, animate=False)` 同步写回。
- 光标仍按条目身份保存/恢复（clear 会重置光标到第 0 行）；assets 下钻的
  esc 同样按身份恢复到出发行。副标题只在内容变化时赋值。
- - **磁盘实扫带 TTL 缓存**（10s）：storage 面板的 `rglob` 在 NFS 上实测 ~105ms，每 2 秒重扫纯属浪费；只缓存扫描（账本部分保持实时——新增/删除数据立刻反映），TTL 过期或数据根不同则重扫。
- 全局刷新周期 `REFRESH_S = 2.0`；`reconcile_aria2()` 每轮照跑（收账闭环）。
- **列宽确定性**：重建时按内容算出每列宽度（`column_widths()`，Rich `cell_len`
  计宽，CJK 算 2 格，上限 `COL_WIDTH_CAP=60`），显式传给 `add_column(width=)`。
  **不要退回 DataTable 的自动列宽**：它在"只有列、还没有行"的首次布局时定宽，
  之后补行不再触发有效布局 → 首屏内容被截断、重建（排序）后才正常。
  真实回归：本地资产首屏文件名显示不全；此前每 2 秒的无条件重建掩盖了它，
  内容签名短路上线后变成持续截断。守卫：`tests/ui/test_refresh.py::`
  `test_first_render_matches_after_rebuild`（首屏 == 刷新后 == 排序后）。

守卫：`tests/ui/test_refresh.py` 直接数**帧**（钩 Compositor.render_update）——
"数据未变 0 帧"、"变化恰 1 帧"、"深滚动重建后仍 1 帧且滚动位置不变"。

### 2.0 面板零：info（数据源注册表）

列：`数据源 | 状态 | 说明`（执行器列已随 E1 移除）。数据来自 SOURCES 的
`SOURCES` 注册表（**单一事实来源**：新增数据源登记一条即自动进面板，
不产生文档漂移）。状态如实含不可达源（asassn/horizons）。

- enter（经 DataTable 的 RowSelected 事件路由，DataTable 会吞 enter 键不冒泡）：
  展开示例代码 + 备注（可直接抄的 fetch 调用）。storage 行无详情，
  enter 走框架回退规则直接下钻
- 下钻不在此面板（挂在 storage——物理层级语义连续；info 是能力参考，不混入存量浏览）
- 明确不做：服务端可下载资源枚举——那是带参数的检索（fetch API/notebook 的职责），
  TUI 无参数输入且网络延迟体验差；如需单独立项（如 ZTF field 浏览器）

### 2.1 面板一：jobs（默认）

**一行 = 一个 job**，列：`job | status | executor | 产出 | error | updated`（时间为本地时区，库内 UTC）

数据流（`_job_rows()`）：

```
astro.db  jobs 表最近 100 条（持久视图：queued/running/done/failed/orphaned）
    ⊕ aria2 RPC tellStatus（实时视图，仅本机 daemon 在线时）
    → 覆盖规则：executor=aria2 且库状态 running 且 RPC 报 active
        → status 列显示 "↓ {pct}% {speed}KB/s"（实时进度）
    → 其余显示库内状态 + error 摘要（36 字符截断）
```

要点：

- **库为准、RPC 为饰**：活动下载的实时进度只覆盖显示，不回写 DB（避免观察
  行为本身制造写放大）；但**终态由 `reconcile_aria2()` 收账回写**——top 每轮
  刷新先调它，把 RPC 报 complete/error 的作业落成 done/failed 并入库 dataset，
  收账不再专属提交进程（wait），观察者驱动的完整闭环
- RPC 不可达（daemon 离线）时静默降级为纯库视图，副标题显示 daemon 离线
- 单个 gid 的 RPC 查询失败被吞掉（job 可能属于已死的 daemon 会话），该行回退库状态

### 2.2 面板二：storage

**一行 = 一个 mission**，列：`mission | 体积 | 文件数 | 备注`

数据流（`_storage_rows()`）：

```
astro.db  files 表全量（path, size）
    → 按 path 相对 data root 的第一级目录聚合（tess/ztf/gaia/ztf-meta/…）
    ⊕ 目录实扫 rglob（data root 真实占用量）
    → 末行 "(目录实扫)"：实扫总量 + 库记录缺失文件数
```

要点：

- **库 vs 磁盘的双向核对**是本面板的存在理由：files 表有记录但文件不在盘上
  （被手动删/移动/NFS 抖动）→ 计入"库记录缺失 N"。这是纯数据库视图做不到的
- macOS 的 `._*` AppleDouble 文件在实扫时排除（NFS 挂载会产生）
- 现版本缺失明细只有计数，没有逐文件列表（见 §7 扩展点）

（原 §2.3 时间线面板已裁撤，裁决见 §2 表格注。）

### 2.3 资产视图（assets）

storage 面板（键 2）在 mission 行按 `enter` 进入，`esc` 返回
（光标按身份恢复到出发行）。列：`dataset | source | 文件名(多文件+N) |
文件✓✗ | 体积(全文件和) | 参数摘要 | created`（本地时间显示）。

## 3. 交互规格

| 键 | 作用域 | 行为 | 实现约束 |
|---|---|---|---|
| `0`/`1`/`2` | 全局 | 切换面板并立即刷新（清空 detail） | `action_pane` |
| `esc` | assets | 返回 storage（光标按身份恢复到出发行） | `action_back` |
| `enter` | 全部 | 打开条目：有详情显详情，无详情则下钻（storage 行 → 资产视图）。jobs 详情 = gid/dataset_id/spec/error；assets 详情 = params + 文件路径 + 类型说明 | 身份寻址：`detail(key)`，key 取选中行首列 |
| `r` | jobs | 重提失败/孤儿作业；done+force=强制重下 | 跨进程可重试：aria2 作业按 url/dest 重建，python 作业按具名 task 重建（E0 起）；仅无 task 的历史闭包作业除外 |
| `x` | jobs | `aria2.remove(gid)` 请求取消活动下载 | 仅对 executor=aria2 且有 gid 的行；remove 对已完成 gid 静默成功 |
| `q` | 全局 | 退出 | — |

底部布局：`#detail` Static（enter 的展开区）+ Footer（键位提示）。状态信息走标准位置：
**header 副标题**（`sub_title`：当前面板名 + aria2 daemon 在线/离线，随 2s 刷新更新——
实时进度列依赖 RPC，离线即降级为纯库视图，这是排查第一入口）；**操作反馈走 `notify()`**
通知浮层（重试/取消结果不再被定时刷新覆盖）。

## 4. 状态语义对照

| 显示 | 含义 | 谁写入 |
|---|---|---|
| `↓ 62% 143KB/s` | aria2 活动下载，实时 | RPC 覆盖，仅显示 |
| `running`（aria2） | 库状态，daemon 在下载但 top 没拿到实时覆盖 | submit 时写 |
| `running`（python） | 调用方进程在执行 | submit 时写 |
| `orphaned` | 心跳超时（`find_orphans`，仅扫 python 执行器） | CLI `myastro orphans` 或外部调用 |
| `failed` | 执行错误（error 列有摘要） | 执行器收账时写 |
| `done` | 完成，dataset_id 已关联 | 收账时写 |

**注意**（与设计文档一致的诚实边界）：aria2 job 的 `running` 状态不参与孤儿扫描——
它的存活由 daemon 与 `.aria2` 控制文件保证；即使没有任何观察者，下载也会继续。

## 5. 线程与一致性模型

- textual 单线程事件循环，`set_interval` 每 2s 跑一次 `refresh_data()`：
  每轮新建 DB 连接、查询、关闭（`DB().init()` → 用完 `close()`）——不跨刷新持有连接，
  避免 sqlite 锁与 NFS 数据目录上的陈旧句柄（库本体在本地盘，见 design-io.md §4）
- aria2 RPC 每轮最多对"库状态 running 的 aria2 job"逐个 `tellStatus`，串行、单次 30s 超时
- 表格每轮全量重建（100 行以内，重建成本可忽略），不做增量 diff——简单性优先

## 6. 行级抽象的裁决（明确不做 RowItem 类）

行级抽象**已存在，以协议形式**：`行 = tuple(首列唯一 key, *cells)`，行为绑定
走 `Pane.detail(key)/drill(key)` 的 key 分发。不升级为"行对象 + 回调"类，理由：

1. **行是短命对象**（每 2s 全量重建）——回调挂行上意味着行为绑定每轮重建、
   闭包易过期、行为定义从 Pane（单一出处）散落为每行一份
2. key 分发 + Pane 方法天然免疫重建：行为住在长命对象上，用稳定身份解析
   （与身份寻址修 bug 同一原理）
3. focus 类交互的正确钩子在 App 层（光标移动事件），与行无关

**重新评估的触发信号**（出现其一再议）：同面板异构行（混排不同行为类型）、
每行上下文菜单（操作超出单键）、多列排序 UI。

**相邻抽象待命**：`filter_mode` 现为 JobsPane 私有；第二个面板需要过滤的那天，
提升为 Pane 基类可选能力（`filter_modes() + apply_filter`，与注册表同构的
能力声明模式）。原则：**抽象跟着第二个实例出现，不跟着想象中的灵活性出现。**

## 7. 已识别的扩展点（未实现，按需追加）

1. **storage 缺失明细钻取**：enter 查看缺失文件逐条列表（现只有计数；assets 下钻已按源给出三态标记）
2. **孤儿标灰/样式区分**：orphaned/failed 行着色（现仅斑马纹）
4. **取消的库回写**：`x` 目前只 remove RPC 侧，jobs 行仍显示 running 直至下次
   `_poll_aria2`（若有 wait 在轮询）或人工 `retry`——可加"cancelled"终态
5. **manifest 内嵌提交**：整份 yaml 在 TUI 内选择提交——已被 `n` 单条下载
   覆盖主要场景，批量仍走 `submit_manifest`，暂不做
