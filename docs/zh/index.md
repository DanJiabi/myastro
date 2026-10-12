# myastro

带账本的个人天文数据工具箱：你手上已经有什么、当初用什么参数取的、文件是否还在盘上。
Python API + CLI + TUI。

## 它做什么

- **取数**：10 个公开巡天（TESS、Gaia、ZTF 元数据/光变/图像帧、Legacy Survey 砖块、
  MPC、SIMBAD、VizieR、unWISE；ASAS-SN 视上游可用性）。
- **账本**：每个数据集（源、参数、文件、sha256 基线）都记进本地 SQLite——
  去重、重试、巡检与覆盖率检查都建在它之上。
- **找回自己的数据**：精确锥搜、关键词检索、对目录索引做覆盖检查。
- **体检**：哈希基线核对、孤儿作业扫描、`doctor` 自检、账本备份/恢复。
- **扩展**：第三方源走插件协议（[插件 API](dev/plugin-api.md)）。

## 安装

```bash
pip install myastro
```

需要 Python ≥ 3.11（macOS/Linux；Windows 未测试）。可选 extras 与 `aria2` 系统依赖见
[安装](install.md)。

## 下一步

- [安装](install.md) —— extras、`aria2`、环境变量
- [快速上手](quickstart.md) —— 第一次取数、TUI、检索自己的归档

## 源码与问题反馈

- 仓库：<https://github.com/DanJiabi/myastro>
- 变更日志：<https://github.com/DanJiabi/myastro/blob/main/CHANGELOG.md>
- 许可：MIT
