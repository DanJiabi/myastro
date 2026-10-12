# 插件协议 v1：给 myastro 加数据源

> 状态：**注册契约（批次 1）、自动发现（2a）与状态可见性（2b）均已落地**。装好插件包即自动生效，
> 不需要用户写 `import`；`myastro doctor` 会报告插件加载状态与失败原因，`sources()` 标注来源。
> 契约变更记录见 `docs/zh/dev/contract-changelog.md`；变更流程见 `docs/zh/dev/change-policy.md`。

## 1. 目标

第三方**不改内核**就能加源：内核（`src/myastro/io/db.py`、`src/myastro/io/jobs/`、
账本 schema、层边界）对插件完全封闭，插件只通过两个公开 API 接入：

```python
import myastro as ma
ma.register_task("mysurvey_fetch", my_fetch_fn)      # ① 任务函数（按名寻址）
ma.register_source(ma.SourceDescriptor(...))          # ② 源描述符（表单/校验/路由）
```

**为什么任务必须按名注册**：`JobSpec` 只存任务名（不存闭包），重试与跨进程恢复都靠它。
传闭包会让作业无法跨进程恢复。

## 2. 最小可用插件

```python
"""my_survey.py —— 一个离线可测的示例插件。

只用公开 API：`ma.FetchResult` / `ma.RunContext` / `ma.write_parquet` /
`ma.register_task` / `ma.register_source` / `ma.FieldSpec` / `ma.SourceDescriptor`。
**
不要**导入 `myastro.io.*`（内核私有，随时可能变）。
"""
import myastro as ma


def my_fetch_fn(ctx: ma.RunContext) -> ma.FetchResult:
    """ctx: RunContext(source, params, dest_dir, cfg)。落盘必须写在 ctx.dest_dir 内。"""
    import pandas as pd

    dest = ctx.dest_dir / f"{ctx.params['target']}.parquet"
    ma.write_parquet(pd.DataFrame({"x": [1, 2, 3]}), dest)   # 走统一落盘（见 processing §8.8）
    return ma.FetchResult(paths=[dest], dataset_id=0, meta={"n": 3})


ma.register_task("mysurvey_fetch", my_fetch_fn)
ma.register_source(ma.SourceDescriptor(
    name="mysurvey",
    desc="我的巡天",
    product="parquet",
    status="ok",
    fields=[ma.FieldSpec("target", label="目标名", pattern=r"^[A-Za-z0-9 _-]{1,32}$")],
    task="mysurvey_fetch",
    example_params={"target": "M31"},
))
```

注册后立即可用：`myastro fetch mysurvey --target M31`、TUI 里 F1 → 选「我的巡天」、
`myastro sources` 列表里出现该源、数据照常入账本并可 `myastro search` 检索。

## 3. 校验规则（注册即 fail-fast）

| 规则 | 说明 |
|---|---|
| 源名 `^[a-z][a-z0-9-]{0,31}$` | 小写字母开头，可含数字/连字符 |
| `desc` / `product` 非空 | 空描述会让 TUI 与 `sources` 无从显示 |
| `status ∈ {ok, degraded, unreachable}` | 与内置源的封闭词汇表一致 |
| `api_version == PLUGIN_API_VERSION` | 不匹配**拒绝注册**（不崩） |
| 字段名唯一且匹配 `^[a-z][a-z0-9_]{0,31}$` | 字段名同时是 CLI 参数名与 TUI 控件 id |
| `pattern` 可编译；`index` 必须存在 | 索引名来自 `src/myastro/io/index.py` 的 `INDEXES` |
| **必须且只能**声明 `task` 或 `url_key` | 两者都没有 = 无法构建作业；都有 = 路由歧义 |
| `task` 必须已在 `TASKS` 里；`url_key` 必须在 `URL_SOURCES` 里 | 先 `register_task` 再 `register_source` |
| `url_key` 源的字符串字段必须有 `pattern`/`name_like`/`choices` | 参数会进 URL 与文件名 → 防路径穿越 |
| `example_params` 必填且**必须通过自己的校验** | TUI 的 F2 示例依赖它；这条能挡住大多数劣质插件 |
| `requires` 里的模块名合法，且声明了就必须给 `install_hint` | `doctor` 用它告诉用户怎么装 |
| `probe_url` 必须是 http(s) | `health` 探针 |
| **内置源名不可覆盖**（连 `replace=True` 也不行） | 内置名保留给本体 |

失败一律抛 `ParamError`（退出码 2），**不留部分状态**；错误信息里带可用取值，便于直接改。

## 4. 禁止事项

- **不要碰账本 schema、作业生命周期、层边界**——那些是内核；
- 落盘只能写在 `ctx.dest_dir` 内（内核有 `_assert_paths_inside_data_root` 兜底，
  越界会被拒，且不会留下半条记录）；
- 不要注册与内置任务同名的任务；不要试图替换内置源；
- 目前**不能**新增 `url_key`（`URL_SOURCES` 不可扩展）——需要 aria2 批量下载能力的插件，
  请在任务内部自行发起请求（或先提 issue 讨论扩展点）。

## 5. 版本与信任

- 协议版本：`myastro.descriptors.PLUGIN_API_VERSION`。插件在描述符里声明 `api_version`；
  不匹配时注册被拒（而不是运行到一半崩）。
- **信任模型**：安装第三方插件 = 信任其代码（等同 `pip install`）。myastro 不做沙箱，
  也不会上传你的任何数据。见 `SECURITY.md`。

## 6. 插件不得扰动本体守卫

契约快照（`docs/contract-snapshot.json`）与守卫**只绑内置源与内置任务**
（`BUILTIN_SOURCES` / `BUILTIN_TASKS`）：装了插件之后 `pytest` 与
`myastro contract-snapshot --check` 必须仍然全绿。
这条由 `tests/kernel/test_plugin_contract.py::test_plugin_does_not_perturb_guards_or_snapshot`
守着——它同时保证快照里的 `fetch <源>` 子命令只收内置源。

## 7. 参考实现与测试

- 内置 10 个源就是协议的参考实现（`src/myastro/descriptors.py` 的 `REGISTRY`）；
- 插件契约测试：`tests/kernel/test_plugin_contract.py`（反例 20 条 + 离线端到端）；
- 扩展点守卫：`tests/guards/test_descriptor_contract.py::test_register_source_extension_point`。

## 8. 后续批次

| 批次 | 内容 | 状态 |
|---|---|---|
| 2a（L3） | **自动发现**：entry-points + `MYASTRO_SOURCES` + 子进程预探测隔离 + 惰性触发 + 恢复兜底 | **已完成** |
| 2b | `doctor` 展示插件状态与失败原因、`sources()` 标注来源 | **已完成** |
| 3 | 仓库内示例插件包 + CI 安装并端到端取一次 | **已完成** |

### 批次 2a：自动发现（0.5.0 起）

**装好即用**：插件包在 `pyproject.toml` 里声明 entry point 即可，用户不需要写任何 `import`：

```toml
[project.entry-points."myastro.sources"]
mysurvey = "my_package.mysurvey"     # 值是模块名；也可写 `模块:注册函数`（可调用则被调用）
```

本机开发（未打包）用环境变量：

```bash
export MYASTRO_SOURCES=my_plugin,another_plugin:register
```

设计要点（细节见 `src/myastro/io/plugins.py` 的模块文档）：

- **惰性**：`import myastro` **不**触发发现；由需要源清单的入口触发一次并缓存
  （`sources()`、按源名查表、`cli.main()` 建解析器之前、以及 runner 的任务解析兜底）。
- **隔离**：先在本进程之外**预探测**（子进程 `import` + 超时），import 阶段挂死/崩溃的插件
  被记为错误并跳过，**不影响主进程**（子进程按结构化标记回报异常类型，诊断精度不减）。
- **恢复兜底**：作业的具名任务若在当前进程的表里找不到，会触发一次发现再解析——
  作业可能是另一个进程创建的。
- **错误可见**：失败插件记一条结构化记录（模块名/异常类型/摘要/建议），由 `doctor` 与
  `sources()` 呈现（批次 2b 接入展示层；现在可用 `myastro.io.plugins.errors()` 读取）。

### 批次 2b：状态可见性（0.5.1 起）

- **`myastro doctor`** 新增「插件（可选）」检查：列出已加载插件；**每个失败插件单独一条 WARN**，
  带异常类型、原因与修复建议（例如协议版本不符会指向本页）。挂死插件报 `ProbeTimeout`，
  但 doctor 本身照常返回——「失败必须可见」与「失败不能拖垮核心」两件事同时成立。
- **`myastro.sources()`** 每一项新增 `origin` 字段：

  | 取值 | 含义 |
  |---|---|
  | `builtin` | myastro 内置源 |
  | `plugin:<模块>` | 由该插件包提供（发现时按「导入前后新增的注册表键」归属） |
  | `runtime` | 插件机制之外显式 `register_source` 注册的源（例如 notebook 里临时加的） |

**信任模型不变**：安装第三方插件 = 信任其代码（预探测只挡"挂死/导入即崩"，
不是沙箱）。见 `SECURITY.md`。

### 批次 3：可运行的参考示例

`examples/myastro-source-example/`（`demo` 源：离线合成光变）——它就是 §2 那段示例的完整可安装版本：

```bash
pip install -e examples/myastro-source-example
python -c "import myastro_example_source" && myastro fetch demo --target M31
```

它同时是**约束的活演示**：只用公开 API、任务按名注册、进文件名的字段声明 `pattern`、
落盘走 `ma.write_parquet` 且写在 `ctx.dest_dir` 内。

守候：`tests/kernel/test_example_plugin.py`（本机导入即注册 → 真取一次 →
断言落盘/入账本/可检索；并断言示例**不导入** `myastro.io.*`，AST 级检查、变异验证可红），
以及 CI 的 build 任务里同名步骤（安装示例包后按文档写法跑一遍）。
