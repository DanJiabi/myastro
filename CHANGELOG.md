# Changelog

本文件记录对使用者有影响的变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.5] - 2026-10-11

### 修复

- **真实取数序列的段错误（SIGSEGV）**：全新数据根下连续
  `myastro fetch ztf-lc …` → `myastro fetch ztf-meta …`，第二个作业在**工作线程**里
  构造 arrow 数组时崩溃（本机实测 10/10 次复现，退出码 139）。
  **触发条件**：pyarrow 的工作发生在**非主线程**里——同序列在调用线程里执行不崩
  （直接调用源函数 0/3、作业同步执行 0/5）。
  **处置**：阻塞式 `fetch` 不再用工作线程，改为在调用线程里执行作业
  （`runner.submit(sync=True)`；`submit` 的异步语义保留给 TUI/批量）。
  修后同一序列 **0/10 崩**、浸泡工具 3/3 通过。
  **如实标注**：① 根因在上游（pyarrow 25.0.0 / pandas 2.3.3 / numpy 2.5.3，
  崩溃率随时序波动，测试中见过 0%–100% 的区间），我们做的是**规避**而非修复；
  ② 逐列构造 arrow 数组、把 pyarrow 线程池钉为 1（两种摆放位置）都**无效**，
  后者已从代码里撤掉（无效的规避手段留在代码里只会变成负担）；
  ③ **残留风险**：TUI/`submit` 路径仍在工作线程里跑作业，未验证；
  ④ pyarrow 26 的对照实验因本机链路无法下载 wheel 而**未完成**。

### 新增

- `scripts/soak_write.py`：在**子进程**里反复跑真实取数序列并统计崩溃率
  （段错误会直接杀掉 pytest 进程，只能在子进程里观测）；区分"崩溃"（信号）
  与"普通失败"（网络/服务），避免 CI 因 IRSA 可用性而红。
- CI 的 build 任务新增该序列的网络冒烟（2 轮）——这是唯一能自动抓住此类崩溃的门。

### 改进

- `core.write_parquet`：逐列用纯 Python 值构造 arrow 数组并显式给类型。
  顺带修好一个真问题——**空表的 dtype 退化**（ibe 检索无命中是常态，
  `pa.array([], from_pandas=True)` 会得到 null 类型，读回来整列就废了），
  并让混合 object 列不再抛 `ArrowTypeError`（统一转字符串）。

### 测试

- `tests/unit/test_parquet_writer.py`（8 条）：数值/字符串/布尔/时间往返、缺失语义、
  坏 UTF-8 不抛错、**空表 schema 保住 double/int64/string**、混合 object 转字符串、
  不写索引、不留 `.tmp`、6 线程并发写不互相干扰，以及**守卫**"必须绕开 pandas 的
  `__arrow_array__` 转换路径"（变异验证：改回 `Table.from_pandas` → 测试立刻红）。

## [0.3.4] - 2026-10-11

### 修复

- **`doctor` 又给出了一条装不上的安装命令**（用户实测）：`pip install 'myastro[asassn]'`
  会在编译 `pyarrow` 时失败——`pyasassn` 0.6.4（2022-06）把 `pyarrow==4.0.1` **精确钉死**，
  而它没有 Python 3.12+ 的轮子。改为 `pip install --no-deps pyasassn`（实测可与新版
  pyarrow 共存），并加测试锁住"提示必须真能跑通"（这次连"extra 名错"和"extra 装不上"
  两类都覆盖）。
- **ASAS-SN 服务不可达时的报错可读性**：`pyasassn` 的客户端在**构造**时就会拉服务端
  schema，失败时用户看到的是一大段 urllib3 重试栈。现在收敛为一句可执行的说明
  （含 `myastro health asassn` 的指引）。

### 文档

- 中英 README 与 `docs/{en,zh}/install.md` 明确写出：`[asassn]` 目前**无法正常安装**
  （上游钉子）与其替代命令；ASAS-SN Sky Patrol v2 端点自 2026-10 拒连
  （`asassn-lb01.ifa.hawaii.edu:9006`），该源在上游恢复前不可用。
- `docs/capabilities.md` 的"休眠源处置"补上三条实测结论。

### 决策记录

- **ASAS-SN 源：保留现状**（2026-10-11）。理由：实现与测试是资产，上游服务迁移
  不等于功能作废；删掉再恢复的成本更高。配套三个**复查触发条件**（写进
  `docs/capabilities.md`）：① 每周 CI 探到 v2 端点恢复可达会自动红并提示做真实验证；
  ② 上游发布解除 pyarrow 钉子的新 `pyasassn` → 纳入必须通过的 extras 矩阵；
  ③ 是否迁移到新版 API 在 0.4.0 之后再评估（优先级低于插件契约）。
  "保留现状"不等于"没人再看"——`asassn-upstream-watch` 就是那个闹钟。

### 新增

- **CI 工作流 `extras.yml`**（手动 + 每周一）：在干净环境里逐个安装我们推荐的 extras，
  把"只会在用户机器上炸"的安装问题提前暴露；`asassn` 作为已知上游问题单独观测
  （装上了就说明上游修好了，届时改为必须通过）。这类问题本该由我们先用 CI 发现，
  而不是让用户撞上。

## [0.3.3] - 2026-10-11

### 新增

- **aria2 依赖的显式检查与指引**（可选系统依赖，只有 Legacy / ZTF 帧 / manifest
  清单需要它）：`myastro doctor` 新增两项——二进制是否存在（缺失时给出
  macOS/Linux 各自的安装命令，并说明"其余源不受影响"）、守护进程状态
  （在线 / 未运行但首次使用会自动拉起 / **在运行但密钥不匹配**）。
- **`MYASTRO_ARIA2_SECRET` / `MYASTRO_ARIA2_PORT`**：RPC 密钥与端口可配置。
  此前密钥是源码里的硬编码常量（`myastro-legacy`）——任何本机进程只要知道这个
  字符串就能通过 6800 端口控制你的 aria2（往数据目录塞下载）。默认值保持不变，
  老用户无需改动。
- 文档（中英 README 与 `docs/{en,zh}/install.md`）新增"可选依赖 aria2"小节，
  含安装命令、自动拉起说明与配置表。

### 修复

- **TUI 新建下载页：快速切换数据源会渲染出错误的字段**（CI 的 macos-3.12 抓到，
  表现为索引标记数对不上；实测旧实现的渲染结果把上一个源的字段和新源的混在一起）：
  `_rendered_key` 曾在 `await remove_children()` **之前**赋值，于是 await 期间到来的
  新选择被判为"已渲染"而跳过，两次重建还可能交错 mount。
  改为 latest-wins：捕获本次 key → 每个 await 点后校验 token → **挂载完成后**才更新
  `_rendered_key`，focus 改为防御式取值（此前在空容器上 `query(Input).first()`
  会抛 `NoMatches`）。
- **并发打开同一个新库会 `database is locked`**：`PRAGMA journal_mode=WAL` 的
  变更**不经过 busy handler**——实测即使 `timeout=5s` 也立刻抛
  `sqlite3.OperationalError: database is locked`。并发 `init` 时必然有一个进程撞上。
  改为**先查再改 + 短重试**（正常情况下库已是 wal，"查"就命中、根本不改动），
  并把 `busy_timeout` 提到连接建立后的第一件事。
  这是 CI 抓到的：**ubuntu 三个矩阵项全红，而 macOS 本地 18/18 全过**（两个平台
  加锁时序不同）——0.3.2 的"并发已修复"结论在 Linux 上并不成立。
- **发布流程漏洞**：0.3.2 的 CI 在 ubuntu 上失败却没人发现，因为我推完快照没看 CI。
  `scripts/publish_public.sh` 现在推完会**等待该提交的 CI 并报告结论**，
  失败则以非零码退出（`--no-wait` 可跳过）。
- **缺少 aria2 时不再白等 10 秒**：旧实现先盲等（20×0.5s）再报一句
  `brew install aria2`（Linux 用户照做不了）。现在先查二进制，缺了立刻报错并给出
  跨平台安装命令。
- **密钥不匹配不再被误报成"离线"**：`ping()` 只有 True/False，用户会按"没启动"去
  排查。现在诊断会区分「没装 / 没起 / 密钥不匹配」，并给出期望的密钥值。
- 测试副作用修复：`ensure_daemon` 的失败路径测试改为替换 `Popen`/`sleep`——
  早期版本会真的尝试拉起 aria2c（本机端口被占才没造成影响），且每个用例白等 10 秒。

## [0.3.2] - 2026-10-11

### 修复

- **并发迁移会把账本弄成"永久打不开"的状态**（用户实测：在新机器上跑
  `myastro init & myastro doctor`，之后每个命令都报
  `sqlite3.OperationalError: duplicate column name: dataset_id`）。
  原因是迁移过程不原子：`executescript()` 会**隐式提交**，拿不住锁，两个进程
  同时从 v1 开始各自执行一遍 `ALTER TABLE`；一旦某个版本的 DDL 提交了、
  版本号却没落下，库就永久卡在"版本落后但列已存在"的残局。
  现在两道保险：
  1. **串行化**：`BEGIN IMMEDIATE` 拿写锁后（10s busy timeout）在锁内重读版本再执行
     DDL，并把迁移改为**单条语句**存储（正是为了不用 `executescript`）；
  2. **幂等**：`ADD COLUMN` 前查 `table_info`，已存在即跳过——上面那种残局**自愈**。
  验证：6 个独立进程并发 init × 3 轮全部成功；构造"版本 1 + 列已存在"的残局后
  `init` 自动修到 8。结构与旧实现逐表逐列比对一致。
- `doctor` 的可选依赖提示给出了不存在的 extra 名（`myastro[pyasassn]`），
  实际是 `myastro[asassn]`——照着提示装会失败。已按"发行名 → extra 名"映射修正，
  并加测试断言提示里的命令真能执行。

## [0.3.1] - 2026-10-10

### 修复

- 抑制 lightkurve 导入期的一条无害提示（`tpfmodel submodule is not available
  without oktopus`）。它出现在**每个新用户的第一个命令**（`myastro doctor`）与首次
  TESS 取数输出里，而该子模块（TPF 像素建模）myastro 从不使用。
  抑制按**消息精确匹配**（`core.quiet_warnings`），其它警告照常暴露；
  测试同时断言"别的警告不会被吞掉"。未选择安装 oktopus：它停留在 2018 年（0.1.2）
  且依赖 autograd，为消一条提示引入它风险更大。

## [0.3.0] - 2026-10-10

**首个公开发布**（0.2.0 为私有基线，未发布）。PyPI 上的起点。

### 新增

- **双语用户文档**：英文 `README.md` + 中文 `README.zh-CN.md`；`docs/en/` 与 `docs/zh/`
  下的安装与快速上手成对存在，并有守卫检查中英章节结构一致（防止只更新一边）。
- **CI（GitHub Actions）**：lint（ruff + pyflakes）、test（ubuntu + macos × Python
  3.11/3.12/3.13，全量离线测试）、build（构建 + `twine check` + 安装 wheel + `doctor` 冒烟）；
  标签发布走 **PyPI Trusted Publishing（OIDC，无长期 token）**，另有 TestPyPI 演练工作流。
- **社区文件**：`CONTRIBUTING.md`（含分层测试规则与"回归测试必须能变红"）、`SECURITY.md`
  （凭据处理与漏洞报告）、`CITATION.cff`、issue/PR 模板。
- `[test]` extra（pytest/pytest-asyncio/ruff/pyflakes），CI 用它而不必装 jupyterlab。

### 变更

- **默认数据根**改为 `~/myastro-data`（此前是本机个人布局）。`doctor` 在未显式设置
  `MYASTRO_DATA` 时给出提示与 export 写法。数据可以放 NAS，账本必须在本地磁盘。
- `githooks/pre-push` 不再硬编码本机环境路径：候选链 `MYASTRO_ENV_BIN` → 仓库内
  `.myastro-env`（gitignore）→ 当前 venv → `.venv` → PATH，每个候选先用
  `pytest --collect-only` 预检；找不到时给出三种修复方式。
- notebook 输出已清空（体积 2.2MB → 28KB），公开仓库不含执行结果。

### 修复

- 发布产物内容明确化：sdist 1.9MB → 179KB（排除 notebooks / `.vscode` / conda 环境记录）。
- 开发向命令（`test-map` / `doc-sync`）在已安装环境里不再抛栈或写入 site-packages，
  改为清晰报错 + 退出码 2。

## [0.2.0] - 2026-10-10

首个打标签的基线（此前为私有开发，未发布）。0.x 阶段允许破坏性变更，但都会写在本文件里。

### 新增

- **数据获取**：10 个描述符源（tess / gaia / ztf / ztf-meta / ztf-lc / mpc / simbad /
  vizier / legacy / unwise），另有 manifest 清单批量下载、exoplanet 目录查询；
  asassn 为休眠源（后端失联）。
- **账本与去重**：SQLite 账本（数据存 UTC，显示转本地时区），缓存键规范化
  （同参数二次调用零网络），`meta_json` 溯源持久化。
- **本地检索**：按源/目标/文件名/时间检索；**精确圆锥坐标检索**
  （入库时解析坐标 → SQL 包围盒粗筛 → haversine 精判 → 按角距排序带 `sep_deg`）。
- **批量与调度**：批次下单与整批重试；launchd 定时任务（健康检查、索引更新）。
- **索引**：legacy-bricks（366k 行）、ztf-fields（1776 场）本地索引，
  前缀查询走缓存 + bisect（实测每次按键 0.5ms）。
- **TUI**（`myastro top`）：三面板（数据源/作业/存储）、F1 新建、F2 预填充、F12 批量；
  索引字段带原生补全（→ 接受）与输入前可见的 `（索引）` 标记。
- **CLI**：20 个子命令；`fetch` 参数由描述符自动生成；`--version`；`init`（建数据根/账本）、`doctor`（环境自检）、`backup`/`restore`（账本备份与恢复）。
- **环境自检**：`ma.doctor()` 检查依赖、路径可写性、账本 schema、**账本文件系统（NFS 上 SQLite WAL 不可用）**、文件抽查、索引、平台能力；有 FAIL 时退出码 1。
- **账本备份/恢复**：`ma.backup()` / `ma.restore()`，SQLite 在线备份 API，恢复默认拒绝覆盖、覆盖前自动留 `.pre-restore-*.bak`、支持旧 schema 备份再迁移。
- **可验证的工程**：能力矩阵（capabilities）+ 生成的测试地图；设计守卫（注册表漂移、
  文档同步、层边界、门面覆盖、落盘路径不变量）。

### 修复

- **路径安全**：名字型参数（`brick`/`ffd`/`target`）此前可经 `..` 把产物写到数据根之外；
  现在输入即拒（`FieldSpec.pattern`/`name_like`）+ 落库前运行时兜底。
- **检索参数**：越界输入（负半径、dec 越界、`limit<1`、日期格式错）此前静默返回空结果，
  其中 `limit=-1` 会按切片语义返回"除最后一条外的全部"；现在一律 `ParamError`。
- **TUI 闪烁**：选中项在视口外时，每 2 秒刷新会先画一帧"列表顶部"再滚回（帧级实测 2 帧/次）；
  现在内容签名短路（无变化不重绘）+ 重建后同步恢复滚动（1 帧）。
- **TUI 首屏列宽**：本地资产首屏"文件名"列被截断（自动列宽在"只有列还没有行"时定宽），
  排序后才正常；现在列宽按内容确定性计算。
- **CLI 错误处理**：`myastro retry 999999` 此前直接抛栈崩溃；现在错误消息 + 退出码
  契约（0/1/2/3/4/5/130）。
- **连接生命周期**：自建 SQLite 连接此前靠 GC 回收；现在用完即关，传入的连接不受影响。

### 变更

- 依赖声明与实际使用对齐：补 `numpy`/`pyarrow`；重依赖移入 `[processing]` extras；
  `pyasassn`/`ztfquery` 为可选后端。
- 采用 MIT 许可。

[0.2.0]: https://github.com/DanJiabi/myastro/releases/tag/v0.2.0
[0.3.1]: https://github.com/DanJiabi/myastro/releases/tag/v0.3.1
[0.3.2]: https://github.com/DanJiabi/myastro/releases/tag/v0.3.2
[0.3.3]: https://github.com/DanJiabi/myastro/releases/tag/v0.3.3
[0.3.4]: https://github.com/DanJiabi/myastro/releases/tag/v0.3.4
[0.3.5]: https://github.com/DanJiabi/myastro/releases/tag/v0.3.5
