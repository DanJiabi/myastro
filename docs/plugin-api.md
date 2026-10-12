# 插件协议 v1：给 myastro 加数据源

> 状态：**批次 1 已落地**（注册契约 + 校验 + 测试）。发现机制（entry-points 自动加载）
> 属批次 2，**尚未实现**——现在需要在插件包被导入时显式调用注册 API。
> 契约变更记录见 `docs/contract-changelog.md`；变更流程见 `docs/change-policy.md`。

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
"""my_survey.py —— 一个离线可测的示例插件。"""
from pathlib import Path

import myastro as ma
from myastro.io.jobs import FetchResult


def my_fetch_fn(ctx) -> FetchResult:
    """ctx: RunContext(source, params, dest_dir, cfg)。落盘必须写在 ctx.dest_dir 内。"""
    import pandas as pd

    dest = ctx.dest_dir / f"{ctx.params['target']}.parquet"
    ma.write_parquet(pd.DataFrame({"x": [1, 2, 3]}), dest)   # 走统一落盘（见 processing §8.8）
    return FetchResult(paths=[dest], dataset_id=0, meta={"n": 3})


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
| 2（L3） | entry-points 组 `myastro.sources` 自动发现 + `MYASTRO_SOURCES` 开发用环境变量 + 加载失败由 `doctor` 报告（不拖垮 CLI/TUI） | 待设计 |
| 3 | 仓库内 `examples/` 示例插件包 + CI 安装并端到端取一次 | 待做 |
