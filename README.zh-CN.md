# myastro

[![CI](https://github.com/DanJiabi/myastro/actions/workflows/ci.yml/badge.svg)](https://github.com/DanJiabi/myastro/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/myastro.svg)](https://pypi.org/project/myastro/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**有记忆的个人天文数据工具箱。** 从公开巡天取数，并在本地账本里记住**你已经有什么**——
不再重复下载同一片天区。

`myastro` 回答普通查询工具不回答的问题：

- "这片天区我下过没有？" → 对账本做**精确圆锥检索**
- "砖块/场号索引里本地占多少？" → 对全量目录算**覆盖率**
- "哪些文件在盘上烂了？" → sha256 基线巡检
- "现在还能取到吗？" → 去重获取 + 源健康探测

三个入口、一份契约：

| 入口 | 用途 |
|---|---|
| 库 | `import myastro as ma`——唯一公开导入（见 `ma.__all__`） |
| CLI | `myastro fetch / search / coverage / audit / doctor / backup …` |
| TUI | `myastro top`——作业/存储/数据源三面板，无需配置文件 |

> 状态：**0.3.0 — alpha**。门面是公开 API，`myastro.io.*` 为内部实现，可能变动。
> 破坏性变更记录在 [CHANGELOG.md](CHANGELOG.md)。

## 安装

```bash
pip install myastro                      # 从 PyPI
pip install -c constraints.txt myastro   # 使用已知可用版本
pip install "myastro[processing]"        # 附测光/成像依赖（规划中的 P2/P3）
myastro doctor                           # 自检：依赖、路径、账本、文件系统
```

需要 Python ≥ 3.11；支持 macOS 与 Linux（Windows 未测试，定时任务仅 macOS/Linux）。
**文档站：** <https://danjiabi.github.io/myastro/>（中文为完整语言，英文含首屏/安装/快速上手）

可选 extras：`[processing]`、`[ztfquery]`、`[asassn]`。

> ⚠️ `[asassn]` 目前**无法正常安装**：`pyasassn` 0.6.4 把 `pyarrow==4.0.1`（2022 年）
> 精确钉死，而它没有 Python 3.12+ 的轮子，pip 会去源码编译并失败。
> 改用 `pip install --no-deps pyasassn`（实测可与新版 pyarrow 共存）。
> 另外 ASAS-SN Sky Patrol v2 端点自 2026-10 起拒连
> （`asassn-lb01.ifa.hawaii.edu:9006`），该源在上游恢复前不可用；
> 用 `myastro health asassn` 查看实时状态。

**可选系统依赖 —— `aria2`**（只影响批量下载：Legacy 砖块、ZTF 帧、YAML 清单；
其余八个源是纯 Python）：

```bash
brew install aria2          # macOS
sudo apt install aria2      # Debian/Ubuntu（Fedora/Arch 用 dnf / pacman）
```

**不需要手动启动守护进程**：首次使用时 myastro 会自己拉起 `aria2c --enable-rpc`。
它用 `MYASTRO_ARIA2_SECRET` 认证（默认 `myastro-legacy`，端口 `MYASTRO_ARIA2_PORT`
默认 6800）——如果你自己起的 daemon 用了别的密钥，设这个变量即可。
`myastro doctor` 会把这几项都列出来。

## 快速上手

```python
import myastro as ma

# 1) 获取——去重：同参数第二次零网络请求
r = ma.fetch("tess", target="WASP-12", sector=20)
print(r.paths[0])

# 2) 这个位置我下过什么？
for hit in ma.search(near=(97.6367, 29.6723), radius_deg=0.5):
    print(f"{hit['source']:10s} sep={hit['sep_deg']:.4f}°  {hit['path']}")

# 3) 对全量索引算覆盖率
print(ma.coverage("legacy-bricks"))      # {'local': 7, 'total': 366912, ...}

# 4) 完整性：先建 sha256 基线，此后检测静默损坏
print(ma.audit())
```

数据根默认 `~/myastro-data`，账本默认 `~/.local/state/myastro/astro.db`，都可用环境变量覆盖：

```bash
export MYASTRO_DATA=/你的/数据根              # 可以放 NAS
export MYASTRO_DB=~/.local/state/myastro/astro.db   # 必须在本地磁盘（SQLite WAL）
```

"数据在 NAS、账本在本地"是预期布局——账本若在 NFS/CIFS 上，`myastro doctor` 会直接判失败。

## 命令行

```bash
myastro init                               # 建数据根与账本（幂等）
myastro doctor                             # 环境自检（有问题时退出码 1）
myastro backup --out ~/myastro-backup      # 账本在线备份 + 清单
myastro restore ~/myastro-backup/<时间戳> --force   # 默认拒绝覆盖
myastro fetch tess --target "WASP-12" --sector 20  # 参数由源描述符自动生成
myastro jobs / wait / retry / delete / retry-batch
myastro search --near 196.18 33.35 --radius 0.2
myastro coverage legacy-bricks
myastro audit                              # sha256 基线 / 损坏报告
myastro index list | index update <name>   # 本地索引（Legacy brick、ZTF 场）
myastro health | schedule install health    # 源探测、launchd 定时（macOS）
myastro top                                # TUI
```

退出码是契约，脚本可据此分流：
`0` 成功 · `1` 部分失败/自检有问题 · `2` 参数错 · `3` 未找到 · `4` 网络 · `5` 状态不允许 · `130` 中断。

## 里面有什么

- **账本**：每次获取都是一个作业；数据集、文件、参数、溯源与坐标都落库。数据文件是事实，账本是索引。
- **去重**：缓存键 = 规范化 `(source, params)` 哈希，同一请求不会再打网络；缓存命中也能回读原始元数据。
- **10 个数据源**：TESS 光变、Gaia DR3 锥检、ZTF 帧/元数据/光变、MPC 历表、SIMBAD、VizieR、
  Legacy Surveys tractor 砖块、unWISE cutout，另有 YAML 清单批量下载。
- **精确圆锥检索**：坐标在入库时解析（params → meta → 索引查询 → 文件名兜底）并落库，
  查询走包围盒 + haversine 精判，按角距排序。
- **本地索引**：36.6 万 Legacy brick、1776 个 ZTF 场；进程内缓存 + 二分查询（TUI 每键 <1ms）。
- **可验证性**：能力矩阵（`docs/zh/dev/capabilities.md`）、生成的测试地图（`docs/zh/dev/test-map.md`）与设计守卫——
  文档或注册表漂移会让测试变红。

## 文档

| 文档 | 语言 | 读者 |
|---|---|---|
| [Install](docs/en/install.md) · [Quick start](docs/en/quickstart.md) | EN | users |
| [安装](docs/zh/install.md) · [快速上手](docs/zh/quickstart.md) | 中文 | 用户 |
| [capabilities.md](docs/zh/dev/capabilities.md) | 中文 | 能力清单与成熟度（最高规划文档） |
| [processing.md](docs/zh/dev/processing.md) | 中文 | 各处理阶段的规则与失败语义 |
| [design-io.md](docs/zh/dev/design-io.md) · [design-top.md](docs/zh/dev/design-top.md) | 中文 | 分层设计与决策 |
| [testing.md](docs/zh/dev/testing.md) · [test-map.md](docs/zh/dev/test-map.md) | 中文 | 测试分层、守卫、生成地图 |
| [release.md](docs/zh/dev/release.md) | 中文 | 发布流程与公开镜像模型 |

用户向文档双语；开发者文档以中文维护。

## 开发

```bash
git clone https://github.com/DanJiabi/myastro && cd myastro
pip install -e ".[dev]"                 # 或 pip install -e . pytest ruff pyflakes
git config core.hooksPath githooks      # 版本化的 pre-push 门（全量 + pyflakes）
pytest -q                               # 372 项测试，离线（网络已打桩）
pytest -m "unit or guards" -q           # 快通道（约 3 秒）
myastro test-map && myastro doc-sync    # 重新生成文档（守卫会在过期时报错）
```

pre-push 钩子自行解析可用解释器（`MYASTRO_ENV_BIN` → `.myastro-env` → 当前 venv →
`.venv` → PATH，每个候选先用 `pytest --collect-only` 预检），并且**不用管道**——
红灯不可能溜过提交门。

## 数据、隐私与凭据

- 一切都在你本机：无遥测、无账号、不上传。
- 只访问公开巡天端点（MAST、IRSA、VizieR、SIMBAD、NERSC、unwise.me）。IRSA 的 ZTF
  元数据可用你自己的工具配置免费账号——**myastro 从不存储凭据**。
- 数据版权属于各巡天项目，本工具只负责获取；使用时请引用对应巡天。

## 许可

MIT——见 [LICENSE](LICENSE)。

<sub>English README: [README.md](README.md)</sub>
