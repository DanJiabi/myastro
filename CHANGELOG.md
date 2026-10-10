# Changelog

本文件记录对使用者有影响的变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
