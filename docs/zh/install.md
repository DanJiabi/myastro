# 安装

## 环境要求

- Python **3.11+**
- macOS 或 Linux（Windows 未测试；定时任务仅 macOS/Linux）
- 账本必须放在**本地磁盘**（SQLite WAL 与 NFS/CIFS 不兼容）。数据文件可以放 NAS。

## 安装包

```bash
pip install myastro
```

可复现安装（使用开发时验证过的版本）：

```bash
pip install -c constraints.txt myastro
```

可选 extras：

| Extra | 内容 | 用途 |
|---|---|---|
| `processing` | photutils、astroalign、ccdproc、scipy、matplotlib、skyfield | notebook 与规划中的测光/成像 |
| `asassn` | pyasassn | 休眠的 ASAS-SN 源 |
| `ztfquery` | ztfquery | 本地构建 ZTF 场索引 |

```bash
pip install "myastro[processing]"
```

## 配置路径

默认值：

| 内容 | 默认 | 覆盖变量 |
|---|---|---|
| 数据根（FITS/parquet） | `~/myastro-data` | `MYASTRO_DATA` |
| 账本（SQLite） | `~/.local/state/myastro/astro.db` | `MYASTRO_DB` |

```bash
export MYASTRO_DATA=/你的/数据根              # 例如 NAS 挂载点
export MYASTRO_DB=~/.local/state/myastro/astro.db
```

若数据放在非默认位置，把这两行写进你的 shell 配置。

## 首次运行

```bash
myastro init      # 创建数据根与账本（幂等）
myastro doctor    # 自检；确实有问题时退出码 1
```

`doctor` 检查：依赖（含 `transitleastsquares >= 2.0`）、数据根与账本目录可写、
账本 schema 版本、**账本所在文件系统**（NFS/CIFS → 失败）、已记录文件的抽样、
索引是否已构建、平台能力。

## 升级 / 卸载

```bash
pip install -U myastro     # 升级；账本会在下次打开时自动迁移
pip uninstall myastro      # 只删代码——数据根与账本不受影响
```

升级大账本之前先备份：

```bash
myastro backup --out ~/myastro-backup
```

## 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `doctor` 报"账本文件系统: nfs" | 账本在网络盘上。把 `MYASTRO_DB` 移到本地磁盘。 |
| `doctor` 报缺少可选依赖 | 装对应 extra，例如 `pip install "myastro[ztfquery]"`。 |
| 获取在重试后仍失败 | 巡天端点在维护或不可达——用 `myastro health` 查看。 |
| `myastro test-map` / `doc-sync` 退出码 2 | 这两个命令只用于源码仓库，安装版不可用。 |
