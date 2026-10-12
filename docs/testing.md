# 测试设计准则

读者：未来的我，以及**只能做有限验证**的项目所有者。本文回答三个问题：
测试放哪里、允许做什么、如何用机器保证"测试确实对应真实需求"。

配套文件：[test-map.md](test-map.md)（能力 → 测试，**生成物**）、
[capabilities.md](capabilities.md)（能力定义与成熟度）。

## 1. 分层与规则

```
tests/
  conftest.py   共享 fixture（env / env_seeded）
  unit/         纯逻辑：无 db、无网络、无 TUI、无真实 fs（tmp_path 除外）
  kernel/       内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/检索/巡检
  sources/      单源契约：只打桩网络层（_download_*），描述符/落盘/入库走真路径
  facade/       门面契约：**只允许 `import myastro as ma`**
  ui/           TUI：headless textual，真 widget；网络与作业启动打桩
  cli/          CLI：子命令参数接线、输出与**退出码**（走门面，隔离外部副作用）
  guards/       设计守卫：静态不变量（漂移、文档同步、边界、覆盖、schema）
```

| 层 | 允许 | 禁止 |
|---|---|---|
| unit | `tmp_path`、numpy/pandas 纯计算 | db / 网络 / textual / 真实 fs |
| kernel | 真 sqlite（tmp）、monkeypatch 网络 | 真实网络、真实 aria2 daemon |
| sources | 真描述符、真落盘、真入库 | 真实网络（只打桩 `_download_*`） |
| facade | `import myastro as ma` | 任何 `myastro.*` 内部模块导入 |
| ui | 真 widget、按键驱动 | 真实网络、真实下载启动 |
| cli | `cli.main([...])`、capsys、临时路径 | 真实网络、真实 launchd、改仓库文档 |
| guards | 静态扫描、注册表、文档 | 业务逻辑（守卫只盯结构与契约） |

边界由 `tests/guards/test_capability_map.py::test_layer_import_boundaries`
**强制**（AST 扫描导入语句），不是口头约定。

**需要隔离系统副作用时**（真 launchd、真 daemon、内部函数），用
`monkeypatch.setattr("myastro.io.xxx.yyy", ...)` 的**字符串路径**——
它不算导入，因此不破坏 facade 层的纯净性（例：
`tests/facade/test_facade.py::test_schedule_list_and_install`）。

## 2. 能力标记与可追溯性

每个测试必须挂**恰好一个**能力标记：

```python
@pytest.mark.cap("acquire.batch")
def test_ztf_excluded_needs_ffd():
    ...
```

能力 id 定义在 `src/myastro/io/testmap.py::CAPABILITIES`，并在
capabilities.md 里以 `<!-- cap:id -->` 标注。`myastro test-map` 生成
[test-map.md](test-map.md)（能力 → 测试清单）。

**四条机器守卫**（`tests/guards/test_capability_map.py`）：

1. 每个测试恰好一个 `cap` 标记（漏挂/重挂即红）
2. 标记 id 必须已注册（配合 `--strict-markers`，拼错即红）
3. 每个注册能力必须有测试（**禁止无人证明的能力声明**）
4. `ma.__all__` 每个门面导出必须被某测试引用（第三方 API 无死角）
5. test-map.md 必须与生成器逐字一致（手改即红）
6. contract-snapshot.json 必须与生成器逐字一致，且与代码一致——契约漂移即红
   （差异定位到叶子路径，见 `tests/guards/test_contract_snapshot.py`）

## 3. 新增能力的标准顺序

```
1. capabilities.md 提升/新增能力行（附 <!-- cap:id -->）
2. io/testmap.py::CAPABILITIES 注册 id 与说明
3. 在对应层写测试，挂 @pytest.mark.cap("<id>")
4. myastro test-map      # 刷新映射
5. pytest && pyflakes    # 提交门
```

## 4. 断言纪律

- **断言必须能失败**。写完回归测试要**变异验证**：把 bug 注入代码，
  确认测试变红；还原后变绿。做过的例子：
  - 下钻返回的"身份寻址"→ 注入"硬编码回第 0 行"⇒ 必须失败
  - ESC 取消路径 → 注入"action_cancel 什么都不做"⇒ 必须失败
  - 新建库 schema 完整性 → 删掉一条迁移 ⇒ 必须失败
- 命名描述**行为**而非函数：`test_cache_hit_returns_meta`，不是
  `test_lookup_cached_2`。
- 不测私有符号（`_foo`）：需要时说明该行为尚未抽象到公开层，
  或把测试移到 guards 层并说明理由。
- 数值断言给容差与理由（如"深度量级 0.003–0.03，明确排除 1−depth 旧语义"）。

## 5. 提交门与 pre-push 钩子

推送前自动跑提交门（**pytest 全量 + pyflakes**），红灯直接中止 push：

```bash
git config core.hooksPath githooks   # 新机器装一次（钩子随仓库版本化）
git push                             # 自动跑门
git push --no-verify                 # 明确跳过（慎用，仅限急事）
```

> **必须全量**（2026-10-09 定案）：钩子跑完整 `pytest`，不做"纯文档改动走快
> 通道"之类的分流——分流的判断本身会出错，而 45 秒的确定性比省下的时间值钱。

钩子在 `githooks/pre-push`（**版本化**，不是 `.git/hooks/`）：解释器按
解析顺序：`MYASTRO_ENV_BIN` → 仓库内 `.myastro-env`（写一行 env 的 bin 目录，已 gitignore）→ 当前虚拟环境 → `.venv` → PATH 上的 python3/python；每个候选都要通过`pytest --collect-only` 预检（只装了 pytest 但缺项目依赖的解释器会被淘汰）。
内部**不经过管道**——`pytest | tail` 会把退出码换成 tail 的 0，红灯溜过门，
这是本项目真实踩过的坑。

## 6. 快慢通道

| 命令 | 用途 | 时长 |
|---|---|---|
| `pytest -m "unit or guards"` | 改代码后随手自检 | ~2 s |
| `pytest` | 全量（提交门） | ~18 s |
| `pytest --cap acquire.retry` | 只跑某项能力的证据（`-m` 只能匹配标记名，不能匹配参数，故提供专用选项） | 秒级 |

`pytest --collect-only -q | grep ::` 可核对用例总数（当前 173）。

## 7. 打桩要打在"使用处"（拆包后的硬规则）

`myastro/io/jobs/` 是包，私有函数按子模块分布。**打桩目标必须是"调用者查表的
那个模块属性"**，否则补丁静默失效（比报错更难查）：

```python
monkeypatch.setattr("myastro.io.jobs.runner._start_aria2_job", fake)  # ✓ 使用处
monkeypatch.setattr("myastro.io.jobs._start_aria2_job", fake)         # ✗ 包名上没有
```

因此包 `__init__` **故意不重导出可打桩的私有函数**——打错目标会立刻
AttributeError，而不是悄悄跑真网络。`_DEFAULT_SESSION` / `_dest_dir_cache`
是原地可变状态对象（conftest 只 `.clear()`），重导出安全。

## 8. 反模式清单（都来自真实返工）

| 反模式 | 例子 | 后果 |
|---|---|---|
| 自比断言 | `n = count(); assert count() == n` | 永不失败，白占一行 |
| 死脚手架 | `for _ in range(0): ...` | 名字承诺的行为从未执行 |
| 名不符实 | `test_delete_key_variants` 只测一个键 | 假覆盖 |
| 测实现细节 | 断言某列存在、某私有函数返回 | 重构即红，需求变了不红 |
| 陈旧引用 | 注释/断言引用已裁撤的面板 | 误导后来者 |
| 无消费者的特性 | 给 `atomic_write` 的返回值写测试 | 守护没人用的东西 |
| 只看 mock | 全打桩后断言 mock 收到的参数 | 没验证真实路径 |
| **自造框架能力** | 自己绑定 Tab 做补全，覆盖了框架的焦点流转 | 交互冲突（焦点被吞）；框架已提供 `suggester` 等机制时应直接用 |

## 9. 何时允许删除测试

- 需求消失（如面板被裁撤）→ 删测试与被测代码
- 被更强的测试覆盖（同层更高层）→ 删弱的
- 休眠源（如 asassn）：**保留**并注明"服务恢复当天需真实验证"，
  同时在 SOURCES note 记录弃用条件（见 capabilities.md §1）
