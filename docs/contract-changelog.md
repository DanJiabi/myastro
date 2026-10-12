# 契约变更记录

> 记录**对外可观察契约**的每一次变化：门面 API、描述符/注册表、CLI 命令与退出码、
> 账本 schema、错误分类。
> 规则见 `docs/change-policy.md` §5；L2 改动必须在动手时同步追加一条。

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
  0 增、0 删、**0 签名变更**（AST 实测；方法见 `docs/change-policy.md` §6）。
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
  漂移由 `tests/guards/` 守卫（见 `docs/test-map.md`）。
- `FieldSpec` 增加 `pattern` / `name_like`（参数校验，防路径穿越）——**加入于 0.2.0 之前**，
  之后未再改判定语义。

### 错误分类（`src/myastro/errors.py` → 门面导出）

- `ParamError`/`NotFoundError`/`NetworkError`/`StateError` + 与退出码的映射；自 0.2.0 起未变。
