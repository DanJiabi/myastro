# 公开发布计划（myastro → PyPI / GitHub）

> 状态：**草案，讨论中**。已定项来自 2026-10-10 的讨论；未定项在 §9 明确标出。
> 本文档取代"随口定的发布流程"：任何发版动作都必须能在这里找到依据。

## 1. 目标与已定的四个决策

| 决策 | 结论 |
|---|---|
| 发布面 | **公开**（PyPI + 公开仓库） |
| 许可 | **MIT** |
| 包名 | **myastro**（PyPI 当前可用，先到先得） |
| 文档 | **双语**：用户向文档中英双语；设计/决策文档中文（附英文摘要） |
| 维护 | 长期维护（见 §8 承诺） |
| 平台 | macOS + **Linux**（用户明确要求支持） |
| 公开账号 | GitHub **DanJiabi**（uid `19997234`，[api 核实](https://api.github.com/users/DanJiabi)） |
| 提交身份 | `DanJiabi <19997234+DanJiabi@users.noreply.github.com>`（GitHub noreply，不公开 163 邮箱） |

## 2. 公开发布要交付什么（"完成"的定义）

1. `pip install myastro` 在干净环境可用，`myastro doctor` 自检通过；
2. 三个入口都有最低可用文档：库（facade）、CLI、TUI；
3. CI 在 Linux + macOS 上跑全量测试与构建，绿了才允许发版；
4. 第三方能**不改内核**加自己的数据源（插件契约）；
5. 明确的"公开 API vs 内部"边界与弃用政策。

## 3. 脱敏清单（公开前逐项确认）

| 位置 | 内容 | 处理 |
|---|---|---|
| `README.md` | 私有远端地址（自建 Gitea + 内网穿透域名） | 已删除，改为公开仓库地址 |
| `docs/zh/dev/testing.md` | 本机 conda 环境路径 | 已改为通用说明（环境变量 / 当前 venv） |
| `src/myastro/io/config.py` | 默认数据根曾是本机个人布局 | 已改为 `~/myastro-data`；`doctor` 在未显式设置 `MYASTRO_DATA` 时提示 |
| `githooks/pre-push` | 解释器探测曾含本机 conda 路径 | 已改为 `MYASTRO_ENV_BIN` → 当前 venv → PATH |
| git 历史 | 作者 `danjiabi <danjiabi@local>`、可能含 NAS 路径 | 决定：全量历史推送（透明）还是新仓 squash（干净）；见 §9 待定项 |
| 提交身份 | 公开仓库的 author/committer 邮箱 | 建议用 GitHub 提供的 `noreply` 邮箱，避免 163 邮箱永久出现在每个 commit 与 PyPI 元数据里 |
| 凭据 | IRSA（ZTF 元数据）账号 | 代码不读取、不存储凭据（已核实）；文档说明"由用户自行配置 ztfquery" |
| 数据 | 数据根内容、账本 DB | **绝不入库**；`.gitignore` 复核 |

## 4. 打包与发布流水线

- 单一版本来源：`myastro.__version__` 由 `importlib.metadata.version("myastro")` 提供 + `myastro --version`；
  `pyproject.toml` 的 `version` 为唯一手写处（或改 `dynamic`）。
- 元数据（PEP 639）：`license = "MIT"`、`license-files = ["LICENSE"]`、`readme = "README.md"`、
  `classifiers`（含 `Programming Language :: Python :: 3.11/3.12/3.13`、`Topic :: Scientific/Engineering :: Astronomy`）、
  `keywords`、`[project.urls]`（Homepage/Documentation/Repository/Issues/Changelog）。
- 构建校验：`python -m build` → `twine check dist/*` → **干净 venv 装 wheel** →
  `myastro --version` + `myastro doctor` 冒烟。
- 发布通道：TestPyPI 先演练；正式走 **PyPI Trusted Publishing（OIDC）**，不用长期 API token。
  启用步骤（一次性）：① 在 PyPI 建项目并添加 trusted publisher（owner=DanJiabi、repo=myastro、workflow=release.yml、environment=pypi）；② 在 GitHub 仓库 Settings → Variables 设 `PYPI_READY=true`；③ TestPyPI 用同样方式配置 environment=testpypi 后手动触发 `testpypi.yml` 演练。在此之前打标签只会跑构建任务，发布任务显示为 skipped（不会造成红灯）。
- 发版脚本 `scripts/release.sh`（幂等、无手工步骤）：干净树检查 → 测试+lint → 构建 → 校验 →
  干净安装冒烟 → 打 tag → 推送 → 上传 → `git push --follow-tags`。

## 5. CI（GitHub Actions）

| 任务 | 矩阵 | 内容 |
|---|---|---|
| test | ubuntu-latest, macos-latest × py3.11/3.12/3.13 | `ruff check`、`pyflakes`、`pytest`（全量，离线） |
| build | ubuntu-latest | `python -m build` + `twine check` + 装 wheel 冒烟 + 上传 artifact |
| docs | ubuntu-latest | `mkdocs build --strict` → 发布 GitHub Pages（见 §5.1） |
| release | tag 触发 | Trusted Publishing 上传 PyPI；生成 GitHub Release（CHANGELOG 段落） |

本地 `githooks/pre-push` 保留为"提交前全量门"（离线可用），但**不再是唯一门禁**。

### 5.1 文档站（GitHub Pages）

- 配置：`mkdocs.yml`（material 主题 + `mkdocs-static-i18n`，folder 结构）。
  **语言策略**：中文是默认且完整的语言（开发文档只写中文）；英文侧只放面向外部读者的
  页面（首屏/安装/快速上手），各自独立 nav。
- 站点：<https://danjiabi.github.io/myastro/>（Pages 的 Build and deployment 设为
  GitHub Actions；工作流 `.github/workflows/docs.yml`）。
- 触发：push 到 main 且改动 `docs/**` / `mkdocs.yml` / 该工作流，或手动 `workflow_dispatch`。
- **`--strict` 是硬要求**：警告（含相对链接写错、页面未在 nav 中）会让构建失败。
  本地先跑一遍再推：`pip install -e ".[docs]" && mkdocs build --strict`。
- 生成物 `docs/contract-snapshot.json` 用 `exclude_docs` 排除（机检产物不是散文）。

## 6. 双语文档结构

```
README.md            英文（PyPI 长描述用这份）
README.zh-CN.md      中文
docs/                （用户向，双语）
  en/{index,install,quickstart,capabilities,api}.md
  zh/{...同一组...}
docs/dev/            （设计/决策，中文 + 英文摘要）
  processing.md design-io.md design-top.md testing.md roadmap-e.md dev-plan.md
docs/zh/dev/test-map.md     生成物（保持中文，属于开发者文档）
```

- 用户向文档必须**成对存在**，加守卫：`docs/en/<name>.md` 与 `docs/zh/<name>.md` 同名成对、章节结构一致（防止单边更新）。注意：计划中的路径要写成 `<name>` 这类模式，否则会被 `tests/guards/test_docs_paths.py` 判为"引用了不存在的文件"——这份草案就被抓过一次。
- 站点：`mkdocs-material` + `mkdocs-static-i18n`；API 页用 `mkdocstrings` 从 docstring 生成（目前 docstring 是中文，需补英文摘要或双语 docstring）。
- notebooks 作为"示例"页（脱敏：去掉个人目标选择与本地路径）。

## 7. Linux 支持工作项（新要求）

| 项 | 现状 | 要做 |
|---|---|---|
| 调度 | `io/schedule.py` 只有 launchd（`~/Library/LaunchAgents` + `launchctl`） | 抽象为后端：macOS=launchd、Linux=**systemd user timer**（优先）或 cron；`myastro schedule` 按平台选择；不支持时明确报错并给出替代命令 |
| 默认路径 | 已改为 `~/myastro-data` ✅ | 不用 `platformdirs.user_data_dir`：macOS 上会落到 `~/Library/Application Support`（不适合放数百 MB FITS）；账本沿用 XDG 路径 |
| 输入法 | `macism`（已 try/except 兜底） | 加 `platform.system() == "Darwin"` 门控，Linux 直接跳过 |
| CI | 无 | 加 ubuntu 矩阵（见 §5），Linux 上跑全量测试 |
| 文档 | 无平台声明 | README 支持矩阵：macOS ✓ / Linux ✓ / Windows 未支持（明确报错而非半坏） |
| 文件系统 | NFS 教训已写入设计文档 | 文档强调"账本必须在本地 FS"（SQLite WAL 与 NFS 不兼容） |

## 8. 长期维护承诺（对外写明）

1. **响应**：issue/PR 两周内首次回应；安全类优先。
2. **版本**：0.x 允许破坏性变更但必须写 CHANGELOG；1.0 后遵循 semver。
3. **弃用**：`DeprecationWarning` + CHANGELOG 标注 + 至少一个 minor 周期后才移除。
4. **依赖**：上游破坏性变更（如 TLS 2.0）→ 提高下限并记 CHANGELOG；Renovate/Dependabot 自动提 PR，但不自动合并。
5. **发布门**：CI 绿 + 干净安装冒烟通过 + CHANGELOG 已更新；缺一不发。
6. **范围克制**：宁可少功能，不做"发了就不管"的承诺。

## 9. 待定项（需要决定）

1. ~~GitHub 用户名~~ → **DanJiabi**；仓库名 `myastro`（PyPI 同名）。
2. ~~公开提交邮箱~~ → **noreply**：`19997234+DanJiabi@users.noreply.github.com`。
3. **历史策略**（唯一剩下的实质性决策）：现有历史的作者是 `danjiabi <danjiabi@local>`，
   与公开身份 `19997234+DanJiabi@users.noreply.github.com` 不一致——推上去后这些提交**不会关联到你的 GitHub 主页**。
   两个选项：
   - **A. 全量历史 + 改写作者**：`git filter-repo --mail-map`（或 `filter-branch`）把作者换成 noreply 后推公开仓；
     保留全部历史与提交信息，但改写后本地与私有远端都要重新对齐（哈希全变）。
   - **B. 公开仓从初始提交开始**：把当前状态压成一个 `Initial public release` 提交推公开仓，
     私有 Gitea 继续保留完整历史。最干净、零风险，代价是公开仓看不到开发过程。
   我倾向 **B**（公开仓以 0.3.0 为起点，诚实写明"此前为私有开发"，对使用者无损失）。
4. **访问方式**：`gh` CLI（推荐，一次 `gh auth login`，凭据进钥匙串）或 SSH key；若坚持用 PAT，需限定细粒度权限（`contents:write`）且不要写入任何被提交的文件。
5. **PyPI 账号**：注册后启用 Trusted Publishing（无需 token）。

## 10. 阶段路线与发布门

| 阶段 | 内容 | 发布门 |
|---|---|---|
| **0.2.0**（私有基线，不上 PyPI） | 冻结当前工作 ✅；版本单一来源 + `--version` ✅；LICENSE/CHANGELOG ✅；`doctor`/`init`/`backup`+`restore` ✅；`constraints.txt` ✅；sdist 内容明确化 ✅；**默认路径平台化 ⏳**（改默认数据根会影响你当前工作流，需先设置 `MYASTRO_DATA`，留到 0.3.0 与迁移提示一起做） | 全量测试绿 ✅ + `twine check` 过 ✅ + 干净 venv 装 wheel 后 `doctor` 过（待打 tag 前复跑） |
| **0.3.0**（首个公开） | **已完成并发布**：GitHub 建仓（快照模型 B）+ 双语文档 + CI 三工作流 + 社区文件 + 脱敏 + 默认数据根平台化 + notebook 清空输出 + PyPI Trusted Publishing | ✅ 全部达成：CI 8/8 绿、PyPI 可装（`pip install myastro` → 0.3.0）、GitHub Release 已建、无个人标识 |
| **0.4–0.9** | 插件式源注册、双语文档站、Linux 调度后端、notebooks 示例、覆盖率 | 每版：CI 绿 + CHANGELOG |
| **1.0** | API 冻结、弃用政策生效、文档补齐 | 公开 API 无未决破坏性变更 |

## 10.1 公开镜像模型（B 方案）与标签约定

公开仓 **不含私有开发历史**：`scripts/publish_public.sh <版本>` 取当前提交的 tree，
创建父提交为"公开分支上一次快照"的提交对象，推送到 GitHub `main`。因此公开历史线性、
每次发布是快进（无需 force push）。

**标签约定**：同名标签在两个仓指向**不同的提交对象、相同的树**——
私有仓的 `vX.Y.Z` 指向 main 的开发提交（便于 `git describe`），
公开仓的 `vX.Y.Z` 指向快照提交。发布脚本会在结束时提示如何把私有仓的标签指回 main。

## 10.2 发布下一版的操作清单（已跑通一次，照做即可）

前提：私有仓改动已提交并通过本地门（`pytest` + `ruff` + `pyflakes`）。

```bash
# 1) 升版本（单一来源：pyproject 唯一手写处）
#    改 pyproject.toml 的 version，并在 CHANGELOG.md 顶部加一段
pip install -e .                       # 刷新可编辑安装的元数据，否则 --version 仍是旧值
myastro --version                      # 应为新版本
# 2) 门 + 生成物
myastro test-map && myastro doc-sync
pytest -q && ruff check src tests && pyflakes src tests
git add -A && git commit -m "release: X.Y.Z" && git push
# 3) 公开快照（自动推 GitHub main 并更新标签，触发 Release 工作流）
scripts/publish_public.sh vX.Y.Z
# 4) 私有仓标签指回 main（脚本会提示）
git tag -f -a vX.Y.Z -m "X.Y.Z" main && git push origin refs/tags/vX.Y.Z
# 5) 发布后核对
gh run list --workflow=release.yml --limit 1
python -c "import json,urllib.request;print(json.load(urllib.request.urlopen('https://pypi.org/pypi/myastro/json'))['info']['version'])"
gh release create vX.Y.Z --title "myastro X.Y.Z" --notes-file /tmp/release_notes.md
```

已知坑：
- **国内镜像（清华等）同步有延迟**：刚发布的版本在镜像上会 `No matching distribution`，
  用 `pip install -i https://pypi.org/simple myastro` 或等镜像同步。
- GitHub 仓库变量 `PYPI_READY=true` 已设置；环境 `pypi` 已加 **required reviewer
  （DanJiabi）+ 部署策略只允许 `v*` 标签**。因此标签推送后：build 自动跑，
  `publish` 会**停在等待审批**（Actions → 该次运行 → Review deployments → Approve）。
  命令行为等价于：
  ```bash
  gh api repos/DanJiabi/myastro/environments/pypi          # 查看保护规则
  gh api --method POST repos/DanJiabi/myastro/actions/runs/<run_id>/pending_deployments \
      -F "environment_ids[]=<id>" -F "state=approved" -f "comment=ok"
  ```
  TestPyPI 环境刻意不加审批：演练是手动触发的，加了只会拖慢。
- TestPyPI 演练需要**单独的账号**与 pending publisher（workflow `testpypi.yml`、
  environment `testpypi`）。**已配置并跑通**（0.3.0）：
  - 触发：`gh workflow run testpypi.yml`
  - 验证要点：TestPyPI 与 PyPI 会有同名同版本，用 **sha256 比对**才能确认来源——
    从 TestPyPI 下载的 wheel 摘要必须等于 TestPyPI JSON API 公布的摘要。
  - 安装验证需带依赖索引：`pip install -i https://test.pypi.org/simple/
    --extra-index-url https://pypi.org/simple myastro`（TestPyPI 不托管依赖）。
  - TestPyPI **不允许重复文件名**：同一版本只能演练一次，下次演练需新版本号。
  - 实测：0.3.0 的 wheel 与 sdist 在 PyPI 与 TestPyPI 上 **sha256 完全相同**
    （两次独立构建字节一致），说明当前 hatchling 构建是可复现的。

## 10.3 发布演练记录（0.3.1，2026-10-11）

首次走完整链路（含新加的人工审批闸门），每步都有可核对的证据：

| 步骤 | 命令 / 动作 | 观察到什么 |
|---|---|---|
| 1 | 改版本 + CHANGELOG + 双语 install 文档；`pip install -e .` | `myastro --version` → 0.3.1（可编辑安装的元数据需重装才刷新） |
| 2 | `pytest && ruff && pyflakes`；`test-map`/`doc-sync` | 375 测试、ruff 0、pyflakes 0；生成物已更新 |
| 3 | `scripts/publish_public.sh v0.3.1` | 公开仓 main 得到快照提交，标签 `v0.3.1` 推送成功 |
| 4 | 标签触发 Release 工作流 | `build` 自动完成；**`publish` 停在 `waiting`**（环境 `pypi` 的 required reviewer 生效） |
| 5 | 人工在 Actions 页面 Review deployments → Approve | `publish` 转 success；日志可见 `Uploading myastro-0.3.1-py3-none-any.whl` |
| 6 | 查询 PyPI JSON API | 一开始仍显示 0.3.0（**API 缓存**），随后 simple index 与 JSON 都出现 0.3.1 |
| 7 | `pip download myastro==0.3.1` | 报 "from versions: 0.3.0" —— **pip 自己的 HTTP 缓存**；加 `--no-cache-dir` 后正常 |
| 8 | sha256 比对 + 装进独立 venv | 下载文件摘要与 PyPI 公布摘要一致；`myastro --version` = 0.3.1、`doctor` 退出码 0 |
| 9 | 验证修复在产物里生效 | 从 PyPI 装的 0.3.1 跑 `doctor`，`tpfmodel` 警告出现 **0 次**（0.3.0 会打印） |
| 10 | `gh release create v0.3.1` | Release 页面生成，Latest 指向 0.3.1 |

**两条新学到的坑**（已写进 §10.2）：发布后立刻查询/安装时，
① PyPI 的 JSON API 与 simple index 有 CDN 缓存；② pip 自身有 HTTP 缓存
（`pip download pkg==新版本` 会看不到，用 `--no-cache-dir`）。

## 11. 0.2.0 冻结计划（已完成，保留作记录）

拆成语义化提交（每个提交都能独立通过全量门）：

1. `fix(paths)`：`FieldSpec.pattern/name_like` + `core.safe_name` + `store._assert_paths_inside_data_root`
   —— `descriptors.py`、`io/core.py`、`io/jobs/store.py`、`tests/unit/test_path_safety.py`、
   `tests/kernel/test_path_containment.py`、`tests/guards/test_descriptor_contract.py`
2. `fix(search)`：查询边界校验 + 门面映射 —— `io/search.py`、`facade.py`、`tests/kernel/test_search.py`、
   `tests/facade/test_facade.py`
3. `fix(cli)`：单连接 + `finally` 关闭 + 退出码 —— `cli.py`
4. `fix(jobs)`：连接生命周期（9 个函数 try/finally）+ 测试 —— `io/jobs/{query,runner,lifecycle,store}.py`、
   `tests/kernel/{test_db,test_jobs,test_batch,test_health,test_schedule}.py`
5. `fix(top)`：列宽确定性（首屏截断回归） —— `io/top/app.py`、`tests/ui/test_refresh.py`
6. `chore(deps)`：依赖声明修正 + extras —— `pyproject.toml`
7. `docs`：processing/design-io/design-top/README + 生成物 —— `docs/*`、`README.md`、`tests/guards/test_registry.py`

冻结后的收尾动作（命令级，避免临场发挥）：

```bash
# 提交身份（仅本仓库，不动全局配置）
git config user.name  DanJiabi
git config user.email 19997234+DanJiabi@users.noreply.github.com

# 每个分组提交后都跑全量门；全部完成后：
#   1) 写 CHANGELOG.md 的 0.2.0 段落（Keep a Changelog 格式）
#   2) myastro test-map && myastro doc-sync，确认生成物最新
#   3) pytest && ruff check src tests && pyflakes src tests
git tag -a v0.2.0 -m "0.2.0：路径安全、检索边界、连接生命周期、列宽回归修复"
git push && git push --tags        # 私有 Gitea（公开仓在 0.3.0 阶段才建）
```

