# myastro 处理逻辑说明

定位：**数据进来之后经历了什么处理、每一步的规则与失败语义**。
与另两份文档互补——[capabilities.md](capabilities.md) 说"有哪些能力、到哪一级"，
[design-io.md](design-io.md) 说"io 层为什么这样分层"，本文说"具体怎么处理"。

面向读者：未来的我、想接手的第三方、想核对行为的你。
每条规则后面都注明**代码位置**与**为什么**（含踩过的坑）。

---

## 0. 全景：一条请求到可检索

```
fetch(source, **params)                      facade.py
  └─ 描述符校验/派生  descriptors.validate → build_spec
       · 类型收敛、choices 校验、缺省补默认、未知键报错
       · task → python 执行器；url_key → aria2 执行器（URL/dest 由 urls.py 派生）
  └─ 缓存短路      jobs.check_cache(cache_key)
       · 命中且文件在盘 → 直接返回（不建 job、不联网）
  └─ 建 job        jobs.submit → 执行
       · python：线程内跑任务函数 + 心跳线程
       · aria2：RPC addUri，落 gid
  └─ 成功          atomic_write 落盘 → jobs._register_success
       · datasets（params_json / cache_key / meta_json / ra / dec）
       · files（path / size / format）
  └─ 失败          jobs.error + jobs.error_type → 门面映射异常类型
  └─ 收账          jobs.wait / jobs.reconcile_aria2（见 §2）
```

---

## 1. 参数与执行器（`src/myastro/descriptors.py`）

| 规则 | 说明 |
|---|---|
| `FieldSpec.type` | 表单/CLI 的类型收敛目标（`str`/`int`/`float`） |
| `default` / `optional` | 空值时的行为：有默认→用默认；`optional`→None；都没有→报"缺少必填参数" |
| `choices` | 有限取值校验（如 cadence、filtercode、band） |
| `index` | 本地索引名 → 表单候选 + 原生补全 + 坐标解析（见 §5）；TUI 在标签上标 `（索引）`，使该能力**输入前可见** |
| `pattern` | 正则全匹配（严格格式，如 `brick` = `^[0-9a-z]{8}$`） |
| `name_like` | 该值会进文件名/目录名 → 走 `core.safe_name`：拒 `/` `\` NUL/控制字符、`.`/`..`、空、>64 字符（见 §3 路径不变量） |
| `label` / `example_params` | 表单标签与示例值的唯一出处（TUI/CLI/文档同源） |

`validate()` 未知键**报错**而不是忽略——防止调用方拼错参数却静默成功。
`build_spec()` 决定执行器：有 `task` → python；有 `url_key` → aria2。
执行器是**实现细节**：门面/CLI/TUI 都不暴露它（有测试守卫）。

`prefill_from_spec()` 是 `build_spec` 的逆映射（F2 预填充）：
描述符命中 → 只填声明的字段（多出的参数丢弃并说明）；
未命中但有 url → 按自定义 URL 填；都不行 → 退化为空白表单并给出原因。

---

## 2. 作业生命周期（`src/myastro/io/jobs/`（包：spec/store/rebuild/aria2_exec/runner/lifecycle/query））

### 2.1 状态机

```
queued ──▶ running ──▶ done
                 └───▶ failed
                 └───▶ orphaned      （心跳超时/提交进程死亡）
```

`updated_at` 兼作心跳（运行中每 `HEARTBEAT_INTERVAL` 秒刷新）。
`verifying` 为保留状态，当前实现不产生。

### 2.2 僵尸判定与重试准入

| 执行器 | 判为僵尸的条件 | 可重试的条件 |
|---|---|---|
| aria2 | daemon 离线，或心跳超时 >5 分钟 | 总是（url/dest 已落库） |
| python | 心跳超时 >5 分钟 | `spec_json` 里有具名 `task` |
| python（旧闭包作业） | 同上 | 不可（无 task 无法跨进程重建） |

跨进程重建 spec 的**优先级顺序**（`_resolve_retry_spec`）：
本进程会话 → aria2 的 url/dest → spec 里的具名 task → **从源描述符推断 task**
（`_infer_task`，救 E0 之前的老作业）。

### 2.3 aria2 收账（`reconcile_aria2`）

- 库为准、RPC 为饰：活动下载的实时进度**只覆盖显示**，不回写 DB（避免观察行为制造写放大）
- 终态必须收账：RPC 报 complete/error → 写 `done`/`failed` 并登记 dataset
- daemon 离线时静默降级为纯库视图（不报错）
- 收账不再专属提交进程：TUI 每轮刷新也会调（观察者驱动的完整闭环）

### 2.4 删除与批次

- 删除 job 记录**保留资产**（files/datasets 不动）——"删记录"与"删数据"是两件事
- 批次 = `batch_id`（migration v4）：状态查询、整批重试（`retry_batch`）以批次为单位
- 健康运行的作业拒绝删除（`StateError`），避免误删在途下载

---

## 3. 落盘与入库

### 3.1 路径不变量：产物必须在数据根之下

两道防线（2026-10-10 加，此前 `brick="../../x"` 实测能写到数据根之外）：

1. **输入即拒**：会把参数拼进文件名/目录名的字段声明 `FieldSpec.name_like`
   （走 `core.safe_name`）或 `pattern`（严格格式）。命中即 `ParamError`，
   在 TUI/CLI 输入阶段就暴露。
2. **运行时兜底**：`jobs/store.py::_assert_paths_inside_data_root` 在**写库之前**
   校验任务返回的每个路径——覆盖"新源忘了标注"，失败不留半条账本记录。

守卫：`tests/guards/test_descriptor_contract.py`（哪些字段必须标注，机制型）、
`tests/unit/test_path_safety.py`（清洗规则）、
`tests/kernel/test_path_containment.py`（运行时兜底）。

| 规则 | 为什么 |
|---|---|
| 原子写：写 `.tmp` → `os.replace` | 下载/转换中断不能污染已有文件；失败时清理临时文件、旧文件不动 |
| 先落盘成功、再写库 | 库里出现记录即代表文件存在（除非事后被外部删除，那由巡检发现） |
| `INSERT OR IGNORE datasets` + **按 cache_key 回查** | 忽略插入时 `lastrowid` 是陈旧值（真实踩坑） |
| `files` 按 path `INSERT OR REPLACE` | 同一路径重复落盘只保留一条记录 |
| `meta_json` 随 `_register_success` 写入 | meta（如 tess 的 ra/dec）必须能在**缓存命中时回读**——曾因不持久化导致 notebook 二次运行 KeyError |
| `error_type` 记录异常类名 | 门面据此把"断网"与"任务 bug"分开（NetworkError vs StateError） |

---

## 4. 坐标解析（`src/myastro/io/coords.py`）

### 4.1 四级解析顺序

```
① params.ra / params.dec          （gaia/simbad/vizier/ztf-lc/unwise 直接带）
② meta.ra / meta.dec              （tess：FITS 头 RA_OBJ/DEC_OBJ 随 meta_json 落库）
③ 源专属 resolver（编号 → 索引 → 坐标）
     ztf / ztf-meta : params.field → ztf-fields 索引
     legacy / legacy-surveys : params.brick → legacy-bricks 索引
④ 文件名兜底                       （tractor-<brick>.fits）
     —— 救"参数只剩 name/url"的快速下载与清单数据
```

### 4.2 规则与边界

- 赤经归一化到 `[0, 360)`；赤纬必须落在 `[-90, 90]`，越界视为解析失败
- **解析失败不报错**（返回 None）：坐标缺失不是错误，只是该数据集不参与坐标检索
- 时机：**入库时解析一次**并写 `datasets.ra/dec`（migration v8 + 位置索引），
  查询时零解析成本，SQL 也能做包围盒粗筛
- 历史数据回填：幂等脚本（按 id 逐行解析后 UPDATE），当前账本 43/47 行有坐标；
  缺口是 mpc（只有天体名，需联网解析）与 index（索引下载本身不是天文数据）

---

## 5. 索引（`src/myastro/io/index.py`）

### 5.1 两类来源

| 类型 | 例子 | 更新方式 |
|---|---|---|
| `url` + `parse` | legacy-bricks（104MB brick 表） | 走 aria2 管线下载 → 解析 → 存 parquet → 删源文件 |
| `builder` | ztf-fields（ztfquery 包内置 1776 场） | 本地构造，**零下载** |

### 5.2 查询与缓存

- 索引落 `data/index/<name>.parquet`；`key_col` 声明键列（默认 `brickname`）
- `load_index` **进程内缓存**（按文件 mtime+size 失效）——
  36 万行 parquet 每次重读 ≈100ms，而 TUI 每个按键都要查
- 前缀查询走**排序键表 + bisect**（O(log n)）：`search_index` 取候选、
  `count_index` 取总数；实测 legacy 每键 0.51ms（此前 ≈230ms）
- `lookup_index`：**精确键 → 整行**（坐标解析用，如 field 673 → 场中心）
- `_save` 后立即失效缓存（更新索引后同一进程立刻看到新数据）

### 5.3 批量资格规则

批量屏（F12）只收录"**索引字段可单独标识一次获取**"的源：
legacy（唯一字段 brick）✓、ztf-meta（其余字段都有默认值）✓、
ztf 帧下载 ✗（还需 ffd，单靠 field 构不出 spec）。

---

## 6. 检索（`src/myastro/io/search.py`）

| 维度 | 语义 |
|---|---|
| `source` / `target` / `name` | 源等值、参数文本子串、文件名子串 |
| `since` / `until` | `created_at` 日期范围（含边界） |
| `near=(ra, dec)` + `radius_deg` | **精确圆锥检索**（见下） |

坐标检索的两段式：

```
SQL 包围盒粗筛： dec ∈ [dec0±r]；ra 窗口按 cos(dec) 放大
                 ra 跨 0° 时拆成两段（359.9 与 0.1 不能当成相距 358°）
   ↓
haversine 精判： 角距 ≤ radius_deg（盒角上的点在这里被剔除）
   ↓
按角距升序 → 带 sep_deg → 截断到 limit
```

**坐标未知的数据集不参与坐标检索**（不是"漏"，是明确语义）。

参数边界（2026-10-10 加）：`radius_deg ∈ (0, 180]`、`near` 的 dec ∈ [-90, 90] 且有限、`limit ≥ 1`、`since/until` 形如 `YYYY-MM-DD[ HH:MM:SS]`——越界一律 `ParamError`。此前这些输入被静默接受（`limit=-1` 甚至按切片语义返回"除最后一条外的全部"）。
该决策的理由：入库时解析 + 存表，换来"查询零解析、SQL 可粗筛"；
代价是历史数据需要回填（已做）。

---

## 7. 巡检与健康

### 7.1 完整性巡检（`io/integrity.py`）

信任模型：**首次巡检建立 sha 基线**（文件在盘 + 尺寸一致即记 sha）；
此后巡检用基线 sha 检测静默损坏（bit rot / 传输残留 / 误写）。
报告字段：`total / ok / missing / size_mismatch / corrupt / baselined`；
明细走 `audit_detail(kind)`。尺寸不符先于 sha 比对（省一次全文件读取）。

### 7.2 源健康探测（`io/health.py`）

判级：连接/DNS 失败 → `unreachable`；HTTP 4xx/5xx → `degraded`；2xx/3xx → `ok`。

**探测深度 = `PROBES` 里填的 URL**——这是硬约束：
只探域名根会**说谎**。真实教训：unwise 根路径恒 200，而真正的
`/cutout_fits` 因参数错误返 500，于是我们误判"服务已恢复"。
凡能给出合法最小请求的源，都必须填该请求。

结果显示：探测结果落 `health` 表，info 面板在 24h 内**覆盖**声明基线（`SOURCES.status`），
过期自动退回基线——两层状态分离（声明 vs 实测）。

---

## 8. 单源特殊处理（服务端契约与坑）

| 源 | 处理要点 | 坑 / 证据 |
|---|---|---|
| **unwise** | `bands` 是**整数位掩码**（1=w1, 2=w2）；响应是 **tar.gz**，需解包出 4 个 FITS（img/invvar/std/n） | 传 `w1` 让服务端 `int('w')` 崩溃返 500；`bands=3` 合并波段返回 0 字节（不支持） |
| **ztf-lc** | 直连 IRSA 原生 `nph_light_curves`（公开数据，**无需凭据**）；锥半径有边界效应 | ztfquery 1.28 的包装器对当前服务端**静默返回空**；5.0004″ 与 5.04″ 差一点点就查不到源 |
| **ztf** | IRSA IBE 路径规则；坐标由 `field` 查 ztf-fields 索引解析 | 图像体积大（~38MB/帧），国际链路 ~84KB/s，批量排夜间 |
| **tess** | lightkurve 检索下载 → parquet；坐标取 FITS 头 `RA_OBJ/DEC_OBJ` 存入 meta | 未归一化通量进 TLS 会静默返回 nan（已在 `lc.transit_search` 内焊死） |
| **gaia** | `columns` 是**可选**参数（描述符不声明该字段） | 曾因实现硬取 `p["columns"]` 导致 KeyError（描述符与实现参数契约不一致） |
| **exoplanet** | 一个行星多组解 → **确定性选择**：优先"周期与深度都非空"，再取周期误差最小者 | 早期"取第一组周期非空的"随归档行序漂移，同一行星两次调用给出不同 T0/深度 |
| **asassn** | **休眠源**：后端 DNS 失联，实现与测试保留防腐烂 | 恢复日需跑一次真实验证；若确认弃用则实现/测试/SOURCES 条目一并删 |
| **mpc / simbad / vizier** | astroquery 封装；空结果不是失败（返回空表 + `empty` 标记） | MPC→SIMBAD 同进程偶发 SIGSEGV（低概率，重试可恢复） |
| **manifest** | YAML 清单 → 逐条 aria2 作业（URL 由 `urls.py` 派生，不手写裸 URL） | 参数只留 name/url → 坐标靠文件名兜底（§4.1 ④） |

凭据现状：ZTF 元数据/图像走 IRSA，本机由用户配置了 IRSA 账号（提高配额）；
ztf-lc 的公开 API 不需要凭据。匿名配额是否够用**未实测**，不写成结论。

---

## 8.5 环境自检与账本备份（2026-10-10 加）

**`myastro doctor`（`ma.doctor()`）**：装完第一件事能自证"这里能不能用"。
检查依赖（含 `transitleastsquares >= 2.0` 硬下限——2.0 起 API 与 1.x 不同）、
数据根/账本目录可写、账本 schema 版本（库里新于代码 → FAIL）、**账本文件系统**
（NFS/CIFS/SMB 上 SQLite WAL 不可用 → FAIL）、文件抽查、索引是否构建、平台能力、
是否在源码仓库。任何单项检查自身出错也会变成一条 FAIL 而不是让 doctor 崩掉；
有 FAIL 时退出码 1，脚本可据此分流。

**`myastro backup` / `restore`（`ma.backup()` / `ma.restore()`）**：账本不可再生
（FITS/parquet 能重下，"取过什么+sha 基线"不能），所以它是唯一必须备份的东西。

- 备份用 SQLite 在线备份 API（`Connection.backup`），**不是 `cp`**：WAL 模式下
  文件复制可能拿到不一致快照。产物 = `astro.db` + `manifest.json`（schema 版本、
  行数、数据根、可选索引清单）。
- 恢复**默认拒绝**覆盖已有账本；`--force` 时先用同一个 API 留存
  `.pre-restore-*.bak`，再**就地覆盖内容**——同样不用文件替换：`cp` + 删
  `-wal`/`-shm` 在"另有连接打开"（TUI 正在跑）时会让后续打开报 `disk I/O error`，
  这个坑在测试里真实出现过。恢复后再跑一次迁移（备份可能是旧 schema）。
- 校验来源：必须是含 datasets/files/jobs 表的 SQLite，且 schema 不超前。

## 8.6 账本迁移的并发与自愈（0.3.2 修）

**规则：迁移必须原子、串行、幂等。**

- **原子**：整段迁移在一个事务里（`BEGIN IMMEDIATE` → DDL → 更新 `user_version` → commit），
  任一步失败则 `rollback`，版本号不前进（否则下次启动会跳过没应用的迁移）。
- **串行**：拿写锁后再读 `user_version` 并在锁内重读，配合 10s `busy_timeout`，
  多个进程同时 `init`（或 TUI 与 CLI 并发）会排队而不是互相踩。
  **不能用 `executescript()`**——它会隐式提交、锁随即丢失；这也是迁移以
  **单条语句元组**存储的原因。
- **幂等**：`ALTER TABLE ... ADD COLUMN` 前查 `table_info`，已存在即跳过。
  这样"版本号落后但列已存在"的残局（并发或中断残留）会**自愈**。

为什么值得这么大动静：迁移失败的代价是**账本永久打不开**——用户实测在新机器上
`myastro init & myastro doctor` 并行后，此后每个命令都报
`duplicate column name: dataset_id`，且没有恢复路径（0.3.2 起自动修好）。

守卫：`tests/kernel/test_db.py::TestMigrationRobustness`——6 个独立进程并发 init、
"版本落后 + 列已存在"残局自愈、迁移失败不推进版本号。

## 9. 失败语义总表（第三方按此分流处置）

| 情形 | 内部行为 | 门面异常 |
|---|---|---|
| 未知源 / 参数拼错 / choices 不符 | `validate` 抛 ValueError | `ParamError` |
| 缓存记录在但文件被删 | 视为未命中，重新获取 | — |
| 网络错误（连接/超时/5xx） | 指数退避重试 1→60s ×5，仅 5xx/网络错 | `NetworkError` |
| 任务函数抛异常 | job → failed，记 `error` + `error_type` | `StateError`（网络类异常映射为 `NetworkError`） |
| 作业不存在 | — | `NotFoundError` |
| 状态不允许（如 done 且 force=False、健康运行中删除） | 拒绝操作 | `StateError` |
| 索引未构建 | 补全降级为 None；表单提示 `myastro index update <name>` | — |
| 坐标解析失败 | 返回 None，不报错 | — |
| 名字型参数含路径元字符（`../`、`/`…） | `FieldSpec.name_like/pattern` 在校验阶段拒绝 | `ParamError` |
| 任务把产物写到数据根之外（新源忘了标注） | `_register_success` 落库前拦截，不留半条记录 | `StateError` |
| 检索参数越界（`radius_deg<=0`、`dec` 越界、`limit<1`、日期格式错） | 显式报错，不返回空结果 | `ParamError` |
| 4xx（非 5xx） | **不重试**（客户端错误重试无意义） | `NetworkError` |

---

## 10. 幂等性与可复现性

- **缓存键** `cache_key(source, params)`：字典序无关、浮点抖动容差
  （0.1 与 0.10000001 同键）→ 同参数二次调用**零网络**
- `params_json` 全量落库 → 任何产物都能反查"当时用什么参数取的"
- `meta_json` 落库 → 缓存命中也能拿到首次下载才有的元信息
- 索引/巡检/健康/调度等"枚举型"操作同样落库或落文件，可重复执行

---

## 11. 代码位置速查

| 处理环节 | 代码 | 测试 |
|---|---|---|
| 参数/描述符/预填充 | `src/myastro/descriptors.py` | `tests/unit/test_prefill.py` |
| 作业生命周期 | `src/myastro/io/jobs/`（包：spec/store/rebuild/aria2_exec/runner/lifecycle/query） | `tests/kernel/test_jobs.py` |
| 账本与迁移 | `src/myastro/io/db.py` | `tests/kernel/test_db.py` |
| 坐标解析/角距 | `src/myastro/io/coords.py` | `tests/kernel/test_coords.py` |
| 索引与缓存 | `src/myastro/io/index.py` | `tests/kernel/test_index.py` |
| 检索（含圆锥） | `src/myastro/io/search.py` | `tests/kernel/test_search.py` |
| 完整性巡检 | `src/myastro/io/integrity.py` | `tests/kernel/test_integrity.py` |
| 健康探测 | `src/myastro/io/health.py` | `tests/kernel/test_health.py` |
| 定时任务 | `src/myastro/io/schedule.py` | `tests/kernel/test_schedule.py` |
| 单源实现 | `src/myastro/io/sources/*.py` | `tests/sources/test_*.py` |
| 门面契约 | `src/myastro/facade.py` | `tests/facade/test_facade.py` |
| TUI 交互 | `src/myastro/io/top/*.py` | `tests/ui/test_*.py` |
| 设计守卫 | `src/myastro/io/testmap.py` | `tests/guards/test_*.py` |
