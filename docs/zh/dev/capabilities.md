# myastro 领域能力清单（master 规划文档） <!-- cap:design.guards -->

版本：0.1｜地位：**最高规划文档**。roadmap 从"做哪个功能"改为"把哪项能力
推进到哪级"；TUI/CLI/文档都是呈现层客户端，不再牵引架构。

## 0. 工作模式与成熟度

```
能力 → 契约（门面 API + 契约测试）→ 内核实现 → 呈现（TUI/CLI/文档）
```

| 级 | 含义 |
|---|---|
| L0 | 缺失 |
| L1 | 内核有实现，无契约 |
| L2 | 契约就绪（门面导出 + 测试 + 文档生成） |
| L3 | 至少一个呈现客户端暴露 |
| L4 | 自动化就绪（无人值守/定时/自愈） |

验收单位是**能力**而非屏幕行为；呈现层 bug（如焦点/布局）不进入本清单。

能力的**证据**在测试层：每个测试挂 `cap` 标记，`myastro test-map` 生成能力→测试映射，四条守卫保证不漂移（见 [testing.md](testing.md)）。

## 1. 数据源管理（source）

| 能力 | 级 | 现状 |
|---|---|---|
| 源注册表（schema 化描述符） | L3 | 10 源；SOURCES/URL_SOURCES/TASKS/INDEXES 四表互指有守卫 | <!-- cap:source.registry -->
| 源健康监测 | L3 | `ma.health()` 端点探测 + 落库 + info 面板新鲜覆盖；实测发现 unwise 已恢复 |。**探测深度=所填 URL**：只探域名根会漏报（unwise 根 200 而 `/cutout_fits` 因参数错返 500）——凡能给出合法最小请求的源都应填该请求 <!-- cap:source.health -->
| 源接入指南 | L1 | 隐含在代码模式里；缺"接一个新源要动哪几处"的 checklist | <!-- cap:source.contract -->
| 契约快照 | 已加 | 门面 `__all__`+参数、CLI 命令（含嵌套）+选项、退出码、账本 schema、注册表名单 → `docs/contract-snapshot.json`；不一致即守卫红，逼着每次契约变化被显式记录 | <!-- cap:design.contract -->
| CI 配置守卫 | 已加 | 工作流 YAML 必须可解析且结构完整（每个 job 有 runs-on/steps）——实测一个步骤名里的冒号就让整个 ci.yml 启动失败，而本地全绿无感 | <!-- cap:ci.config -->
| 休眠源处置 | 决策已定（2026-10-11 明确：**保留现状**） | asassn（后端失联）保留实现+测试防腐烂，恢复日做真实验证；弃用则代码/测试/注册表一并删。**复查触发条件**：① `extras.yml` 每周探测到 v2 端点恢复可达（会自动红并提示做真实验证）；② 上游发布新版 `pyasassn`（解除 pyarrow 钉子）→ 把 `asassn` 移入必须通过的 extras 矩阵；③ 决定迁移到新版 API（0.4.0 之后再评估，其优先级低于插件契约）。**实测补充（2026-10）**：① v2 端点 `asassn-lb01.ifa.hawaii.edu:9006` 拒连（`health asassn` 报 unreachable）；② `pyasassn` 0.6.4 钉死 `pyarrow==4.0.1`，Python 3.12+ 装不上，只能用 `pip install --no-deps pyasassn`；③ 连接失败已收敛为一句可执行提示（不再抛原始 urllib3 栈） | <!-- cap:source.dormant -->
| 凭据管理 | L1 | IRSA 账号手动配 ~/.ztfquery；无统一凭据层 |

## 2. 下载管理（acquire）

| 能力 | 级 | 现状 |
|---|---|---|
| 单件获取 fetch（缓存幂等） | L3 | 门面 + TUI + CLI | <!-- cap:acquire.fetch -->
| 计划型查询 query（不落盘） | L3 | | <!-- cap:acquire.query -->
| 批量 batch（批次生命周期） | L3 | 提交/查看/`ma.retry_batch`（失败半批一键重跑）/CLI retry-batch | <!-- cap:acquire.batch --> <!-- cap:acquire.manifest -->
| 重试/强制重下/删除 | L3 | 含跨进程重建、僵尸判定 | <!-- cap:acquire.retry --> <!-- cap:acquire.cancel -->
| 断点续传 | L2 | aria2 原生，依赖 daemon 存活 |
| 定时获取 schedule | L3 | launchd 代理（health 每日/index 每周），`myastro schedule list/install/remove`；调度不自建 | <!-- cap:acquire.schedule -->
| 带宽礼仪 | L1 | IRSA 夜间建议靠文档；无速率配置 |

## 3. 数据管理（ledger，本地/云端共管）

| 能力 | 级 | 现状 |
|---|---|---|
| 溯源账本（params 可反查） | L3 | datasets/files/jobs 三表 | <!-- cap:manage.ledger -->
| 文件在盘核对 | L2 | exists 三态标记（storage/assets/jobs 产出列） |
| 完整性校验 | L3 | `ma.audit()` sha 基线+核对（首次建基线，此后测损坏）+ `audit_detail`；CLI `myastro audit`；实测 25 文件基线建立 | <!-- cap:manage.integrity -->
| 环境自检 `doctor` | L3 | 依赖/路径可写/账本/文件系统/索引/平台；退出码 1 表示有 FAIL | <!-- cap:manage.doctor -->
| 账本备份与恢复 | L3 | `ma.backup()` / `ma.restore()`；SQLite 在线备份、默认拒绝覆盖、覆盖前留 `.pre-restore-*.bak` | <!-- cap:manage.backup -->
| 索引浏览 + ✓/☁ 共管视图 | L3 | 批量屏；索引两枚：legacy-bricks（36 万，url 型）/ ztf-fields（1776，builder 型本地构造）；批量资格=索引字段可单独标识获取 | <!-- cap:manage.index -->
| 按需云端下载 | L3 | 同屏勾选 ☁ → Ctrl+S |
| 覆盖率统计 | L3 | `ma.coverage(index)`；实测 legacy-bricks 7/366912 | <!-- cap:manage.coverage -->
| 本地检索（按坐标/时间/目标查已有） | L3 | `ma.search(target/near/since/name)` + CLI `--near/--radius`；**坐标精确化**：入库时解析（params/meta/编号→索引/文件名兜底）存 `datasets.ra/dec`，查询走 SQL 包围盒 + haversine 精判、按角距排序带 sep_deg | <!-- cap:manage.search -->
| 保留策略 retention | L0 | 无"旧 job 归档、冷数据清理"策略 |

## 4. 数据处理（process）——逐步拓展，先立边界

**边界**：处理逻辑住在 notebook/脚本层（用户域），myastro 的职责是
**保证原料稳定**（schema 契约）+ **供处理层调用的最小工具**。

判据：**"换个目标还会一模一样地做"的进库**（纯变换、可测试、契约稳定），
**"取决于这次想干什么"的留 notebook**（选目标、挑参数、画图、叙述）。

| 能力 | 级 | 现状 |
|---|---|---|
| 产物 schema 稳定承诺 | L2 | SCHEMA_VERSION=1 声明；列名即契约 |
| 处理示例 | L3 | 三个阶梯 notebook（凌星/造父/ZTF 差分） |
| **lc 时序工具库** | **L3** | 9 函数（归一化/筛选/折叠/分箱/幅度/周期搜索/凌星搜索）+ 17 测试；01/02 两片 notebook 已重构使用，数字与重构前逐项对账一致 | <!-- cap:process.lc -->
| phot 测光工具库 | L0 | 下一步 P2（检测/孔径测光/Gaia G 定标打底、APASS 校验） |
| imaging 图像工具库 | L0 | P3（对齐/叠加/差分），智能望远镜到手后做 |
| 派生产物目录约定 | 决策已定 | `data/derived/<目标>/`，与原始数据物理分离；实现待 P4 |
| 派生数据集溯源（derived_from） | L0 | P4：产物入账本、可反查原料 dataset 与处理参数 |
| 管线编排（处理链描述/重跑） | L0 | 远期；防止过度设计先不做 |

> **教训载体**：库函数不只是去重，还承载 notebook 里以文字记录的坑——
> `transit_search` 内部强制归一化（否则 TLS 静默 nan）并返回真深度
> （TLS `depth` 是凌内/凌外比）；`period_search` 默认 LS+PDM 两步
> （LS 对非正弦光变系统性偏峰）。测试里有对应的回归项。

## 5. 格式转换（convert）——领域概念确认

天文领域该概念**真实存在且分两层**，但须防"格式金字塔"。
原则：**正典格式 + 边缘按需转换**（正典 = 表格 parquet / 图像 fits）。

| 能力 | 级 | 现状 |
|---|---|---|
| 文件格式（fits 表 → parquet） | L1 | 隐式散在源实现里（tess/meta 即转换） |
| 时间系统（JD/MJD/BJD ↔ 相位） | L1 | notebook 手写；无统一工具 |
| 星等 ↔ 流量（含归一化） | L1 | 项目 2 手写 f/median；ZTF mag 列原生 |
| 坐标系（ICRS ↔ Galactic） | L0 | astropy 一行的事，按需暴露 |
| 互操作导出（CSV/AstroImageJ/VStar） | L0 | 有真实场景（AAVSO 上报）再做 |

> 判断标准：转换能力只在**第二个真实消费者出现**时升 L2（老规矩）。

## 6. 呈现层（presentation，非能力域）

| 客户端 | 现状 |
|---|---|
| TUI（top） | 三面板 + 新建/批量/**预填充**模态（F1 新建、F2 从选中作业预填）；身份寻址契约 | <!-- cap:present.tui -->
| CLI | 16 子命令：fetch 参数由描述符自动生成；错误→退出码 2/3/4/5 | <!-- cap:present.cli -->
| 文档 | 矩阵生成（doc-sync）；API 参考未生成 |
| 第三方 | 门面 + 错误契约（含作业失败类型映射）+ 扩展点 register_source + `ma.prefill`（spec→表单，客户端共用） | <!-- cap:facade.api -->

## 7. 当前最高价值的缺口（按能力排序）

3. **保留策略 retention**（L0）：job 归档、冷数据清理
4. **本地检索坐标精确化**：现为 params 粗匹配，量级上来后需空间索引

## 8. 维护纪律

- 本文档随能力变动更新（提交含能力变化时必须同步）
- 新工作入队格式："把 X 能力从 Ln 推到 Lm"，呈现层工作单列
- 每次架构 review 对照本文档检查：是否有能力降级/无契约实现
