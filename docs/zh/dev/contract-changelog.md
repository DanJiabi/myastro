# 契约变更记录

> 记录**对外可观察契约**的每一次变化：门面 API、描述符/注册表、CLI 命令与退出码、
> 账本 schema、错误分类。
> 规则见 `docs/zh/dev/change-policy.md` §5；L2 改动必须在动手时同步追加一条。

## 记录格式

| 日期 | 版本 | 契约点 | 变更 | 理由 | 兼容性 | 守卫/测试 |
|---|---|---|---|---|---|---|
| 2026-10-11 | 0.3.5 | 作业执行模型（`jobs.runner.fetch`） | 阻塞式 `fetch` 改为**在调用线程里执行作业**（`submit(sync=True)`）；`submit` 的异步语义不变 | 非主线程里跑 pyarrow 会段错误（实测 10/10），规避见 CHANGELOG 0.3.5 | 对外行为不变（`fetch` 仍是阻塞语义，返回值不变）；`submit` 调用方不受影响 | `tests/unit/test_parquet_writer.py`、CI 真实序列冒烟（`scripts/soak_write.py`） |

| 2026-10-11 | **0.4.0** | CLI dev 命令集 | 新增 `contract-snapshot [--check]`（24 → 25 个子命令） | 契约漂移必须可机检：生成 `docs/contract-snapshot.json` 并由守卫比对 | 纯新增；不影响既有命令、参数与退出码 | `tests/guards/test_contract_snapshot.py`（含三种变异验证）、`tests/kernel/test_contract.py` |

| 2026-10-11 | **0.4.0** | **插件协议 v1** | ① `SourceDescriptor` 新增 `api_version`/`requires`/`install_hint`/`probe_url`（全有默认值）；② `register_source(..., replace=False)` 新增参数并接入注册校验；③ 新增公开 API `register_task(name, fn, *, replace=False)`（`__all__` 33 → 34） | 第三方源无法在"不改内核"的前提下接入：注册入口缺校验、任务函数无注册途径 | **纯新增**：内置 10 源用默认值，行为与签名调用方式不变（`register_source(d)` 仍可用）；插件协议版本化，不匹配拒绝注册 | `tests/kernel/test_plugin_contract.py`（33 条，含 20 条反例与离线端到端）；契约快照守卫如实报出上述 6 处叶子变化后重新生成 |

### 1b：快照与守卫只绑内置（同日，随插件协议 v1）

`contract.snapshot()` 的 `registries` 与 `cli.commands` 现在**只收内置**
（`builtin_registry()` / `BUILTIN_TASKS` / `BUILTIN_SOURCES`）：`fetch <源>` 是按注册表
动态生成的，若不过滤，用户装一个插件就会让 `--check` 与守卫假红。
两个原本遍历全量注册表的守卫（`test_descriptor_fields_cover_task_params`、
`test_task_registry_and_descriptors_agree`）同样改为只绑内置。
验收测试：`tests/kernel/test_plugin_contract.py::test_plugin_does_not_perturb_guards_or_snapshot`
（注册插件后快照字节不变）。

| 2026-10-12 | **0.4.1** | 插件作者公开面 | 新增公开导出 `write_parquet` / `FetchResult` / `RunContext`（`__all__` 34 → 37）；`facade.PLUGIN_EXPORTS` 声明这三者 | **0.4.0 实测缺陷**：协议要求任务返回 `FetchResult`、用统一落盘，但这三个名字当时没有公开，`docs/zh/dev/plugin-api.md` 的示例照着写在已安装的 wheel 上直接失败（`module 'myastro' has no attribute 'write_parquet'`） | 纯新增；无破坏性变化 | `tests/kernel/test_plugin_contract.py::test_plugin_doc_example_uses_public_api_only`（解析文档里的 `ma.<名>` 是否都在 `__all__`，变异验证可红）+ 端到端改用纯公开 API |

| 2026-10-12 | **0.4.2** | ① 处理层公开面：`lc` 纳入 `__all__`（37 → 38）；② `lc.transit_search` 新增可选 `r_star`/`m_star`；③ 契约守卫覆盖公开子模块 | ① 处理层一直通过 `from myastro import lc` 使用，却是"事实公开、名义未导出"；② TLS 无恒星参数时按 1.0/1.0 估周期网格并警告（指向真问题，故暴露参数而非抑制）；③ **守卫覆盖漏洞**：快照初版只记 `__all__` 条目名，子模块内的签名变化逃过检查（实测：加参数后仍报"一致"） | 纯新增：`transit_search` 旧调用不变；`lc` 此前即可用（`from myastro import lc`），现在正式导出 | `tests/kernel/test_contract.py::test_covers_public_submodule_exports`（锁住子模块覆盖 + 恒星参数在快照里）；`tests/unit/test_lc.py::TestStellarParams`（转发 + 真实跑一次无警告） |

| 2026-10-12 | **0.4.3** | 文档架构与安装面 | ① 文档树重构为 `docs/{zh,en}`（中文开发文档进 `docs/zh/dev/`）；② 新增 `[docs]` extra（mkdocs-material + mkdocs-static-i18n）并并入 `[dev]`；③ 双语配对守卫规则升级为"英文页必须在中文有同名对应" | 为发布双语文档站做准备；`[docs]` 让贡献者一条命令装齐站点依赖 | ① 文档路径变化（对外链接会变，README/CHANGELOG 已同步）；② 纯新增 extra；③ 守卫规则收紧（英文孤儿页现在会红） | `tests/guards/test_docs_paths.py`（递归扫描 + 配对规则）、`mkdocs build --strict`（CI docs 工作流） |

| 2026-10-12 | **0.5.0** | 源发现与任务解析 | ① 新增自动发现：entry-points 组 `myastro.sources` + `MYASTRO_SOURCES`；② `sources()` / 按源名查表 / `cli.main()` / runner 任务解析 触发惰性发现；③ 任务解析失败改为落成**作业失败**（原会拖死工作线程） | 装插件后仍需用户手写 import 才能用；且解析失败会让作业永远停在 running | 纯新增能力：不装插件时行为与 0.4.x 一致（快照/守卫仍只绑内置）；显式 import 的旧用法仍可用 | `tests/kernel/test_plugin_discovery.py`（25 条，含三条变异验证）、CI 的示例插件步骤（**不显式 import** 也须取数成功） |

| 2026-10-12 | **0.5.1** | 插件状态可见性 | ① `myastro.sources()` 每项新增 `origin` 字段（`builtin` / `plugin:<模块>` / `runtime`）；② `doctor` 新增「插件（可选）」检查组（已加载列表 + 每个失败插件一条 WARN，带类型/原因/建议） | 插件失败已被隔离，但**用户看不见**——等于把失败静默吞掉；来源也无法回答「这个源是谁提供的」 | 纯新增字段与检查项：不装插件时 `origin` 恒为 `builtin`、doctor 多一条 OK；既有调用方按名取键不受影响 | `tests/kernel/test_plugin_discovery.py`（32 条，含三条变异验证：去掉 origin 字段 / 摘掉 doctor 检查 / 清空失败展示循环，均确认真能红） |

> 已知覆盖缺口（如实记录）：契约快照只覆盖**函数签名**，`sources()` 返回字典里**新增字段**这类行为契约不会被快照捕获——本次靠人工登记。是否把返回结构也纳入快照，留待后续评估（见 `docs/zh/dev/change-policy.md` §5）。

| 2026-10-13 | 未发布（随下一版） | `lc.transit_search` 恒星参数语义 | `r_star`/`m_star` 点值改为 ±10% 展开为区间，并支持 `(value, min, max)` 三元组 | **真实使用暴露**：0.4.2 初版只传点值不传 min/max，TLS 的 M_star_max 默认恰好 1.0，任何超太阳质量的星（如 WASP-12 M=1.47）被直接拒绝——项目 1 流程走通时撞到 | 纯修复：旧调用（不传/传点值≤1.0）行为不变 | `tests/unit/test_lc.py::test_real_run_with_super_solar_mass`（M=1.47 回归）+ 转发断言（点值展开/三元组） |

| 2026-10-13 | 未发布（随下一版） | ① CLI 新增子命令 `describe`（单源详细中文描述）与 `version`（版本身份块）；② `SourceDescriptor` 新增可选字段 `detail`；③ `sources()` 字段字典新增 `optional` 键；④ ztf-lc 一句话描述修正（“IRSA 凭据”→“匿名可用”，过期信息） | 用户要求：源详情要在 CLI/TUI 可见；version 便于报 bug；ztf-lc 描述是过期错误信息 | 全部纯新增/文案修正，无破坏性变化 | `tests/cli`（describe/version）、`tests/ui/test_source_detail.py`（TUI 详情面板+Header 版本，变异验证可红）、`test_builtin_sources_have_nontrivial_detail`（文案契约，变异验证可红） |

| 2026-10-13 | 未发布（随下一版） | ① CLI 新增子命令 `preview`（本地文件预览）；② 门面新增 `preview(target, lines)`（`__all__` 38 → 39，支持 `#数据集id` 账本解析）；③ `sources()` 字段字典新增 `optional` 键 | 用户要求：不打开 pandas/FITS 工具就能快速确认"账本说我有"的数据是什么 | 纯新增；无破坏性变化 | `tests/kernel/test_preview.py`（嗅探/parquet/FITS/文本，gzip 变异验证可红）、`test_facade_preview.py`（#id 解析与错误映射）、CLI/TUI 按键测试（绑定变异验证可红） |

## 快照机制的建立（2026-10-11）

- 生成器 `src/myastro/contract.py`（顶层模块——放 `io/` 会违反分层：内核不许依赖 `cli`）。
- 覆盖：`facade_api` / `cli`（含嵌套子命令）/ `exit_codes` / `ledger_schema` / `registries`。
- 守卫：`tests/guards/test_contract_snapshot.py`，差异**定位到叶子路径**，
  并断言快照是生成器的逐字节结果（手工编辑即红）。
- 从此 §5 的"人工维护"改为**由守卫强制**：任何契约变化都必须显式重新生成快照
  并在本文件追加一行。

## 回溯基线（0.1 → 0.3.5，一次性补记）

这些变更发生在本文档建立之前，按现有代码与 CHANGELOG 回溯登记，作为后续对照的起点。

### 账本 schema（`src/myastro/io/db.py`）

| 版本 | 内容 | 引入于 |
|---|---|---|
| v1 | `datasets` / `files` / `jobs` 三表与索引 | 2026-10-08 |
| v2 | `jobs.dataset_id` | 2026-10-08 |
| v3–v5 | 作业状态机与错误分类相关列 | 2026-10-08 |
| v6 | `jobs.error_type`（错误分类，供 CLI 退出码分流） | 2026-10-09 |
| v7 | `jobs.meta_json`（结果元数据） | 2026-10-09 |
| v8 | `datasets.ra` / `dec`（精确锥搜，入库时解析坐标） | 2026-10-09 |

**破坏性迁移 0 次**（无 DROP/改列/改类型）。**v1–v8 全部在 0.2.0 之前定型，
0.2.0 以来 schema 零变化**；后续若需变更，按 L2 流程走。

### 门面 API（`__all__` 定义在 `src/myastro/__init__.py`，函数在 `src/myastro/facade.py`）

- **自 0.2.0 起零漂移**：`__all__` 一直 **33 项**；facade 一直 **27 个函数**，
  0 增、0 删、**0 签名变更**（AST 实测；方法见 `docs/zh/dev/change-policy.md` §6）。
- 覆盖面：`fetch`/`batch`/`retry`/`search`/`coverage`/`audit`/`health`/`index_*`、
  账本运维（`doctor`/`backup`/`restore`）、处理层（`lc.*`）、错误类型与 `FieldSpec`/`SourceDescriptor`。
- 订正：本表初版写的"16 → 37（+21）"是用正则数 `facade.py` 里的引号字符串得到的**错数**。

### CLI 命令与退出码（`src/myastro/cli.py`）

- **自 0.2.0 起零漂移**：24 个子命令在 0.2.0 与 HEAD 完全相同（含 `init`/`doctor`/`backup`/
  `restore`/`test-map`/`doc-sync`）。
- 退出码契约（`cli.EXIT_CODES`）：`0` 正常、`1` 部分失败/自检有问题、`2` 参数、`3` 未找到、
  `4` 网络、`5` 状态、`130` 中断。**自 0.2.0 起未变**。

### 注册表（`src/myastro/descriptors.py`、`src/myastro/io/urls.py`、`src/myastro/tasks.py`）

- 描述符源 10 个、URL 源 2 个（`legacy`/`ztf`）、任务表与描述符一一对应；
  漂移由 `tests/guards/` 守卫（见 `docs/zh/dev/test-map.md`）。
- `FieldSpec` 增加 `pattern` / `name_like`（参数校验，防路径穿越）——**加入于 0.2.0 之前**，
  之后未再改判定语义。

### 错误分类（`src/myastro/errors.py` → 门面导出）

- `ParamError`/`NotFoundError`/`NetworkError`/`StateError` + 与退出码的映射；自 0.2.0 起未变。
