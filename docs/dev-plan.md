# myastro 开发计划（第一阶段，已归档）

> **状态：M1–M7 全部完成（2026-10），本文档为历史归档**。
> 现行规划见 [capabilities.md](capabilities.md)（能力清单，最高文档）与
> [roadmap-e.md](roadmap-e.md)（E 系列）。

版本：1.0｜依据：docs/design-io.md（v1.0 定稿）

## 里程碑

### M1 — 基础设施：core + db

**交付**
- `io/config.py`：`Config`——读 `MYASTRO_DATA`（默认 `~/myastro-data`）、`MYASTRO_DB`
  （默认 `~/.local/state/myastro/astro.db`），初始化目录
- `io/core.py`：
  - `cache_key(source, params)`：参数规范化（键排序、浮点定精度）后哈希
  - `retry(fn, attempts=5)`：指数退避 1→60s，仅网络错/5xx 重试，4xx 直接抛
  - `atomic_write(path, write_fn)`：`.tmp` → `os.replace()`，异常清理
- `io/db.py`：`DB`——本地路径连接（WAL）、建表（datasets/files/jobs，`updated_at` 心跳）、
  `PRAGMA user_version` 迁移

**测试**：cache_key 稳定性（乱序 dict 同 key）；retry（5xx×3 后成功、4xx 不重试）；建表与迁移
**验收**：pytest 全绿；真实路径建出 astro.db

### M2 — 作业基底：python 执行器

**交付**
- `io/jobs.py`：`JobSpec`、`submit(spec)`（缓存命中不建 job）、python 执行器
  （目标函数包装，5s 心跳刷 `updated_at`）、`wait/status/retry`、`fetch(spec)`（submit+wait 糖）
- CLI 骨架：`myastro jobs` / `myastro retry N`（pyproject `[project.scripts]`）

**慢网络语义（关键验收项）**
- 超时默认从宽（30 分钟级）；**有心跳 = 慢（继续等），无心跳超时 = 死（标 orphaned）**，
  不用单纯 wall-clock 超时判死
- 内层 HTTP 超时透传：lightkurve/astroquery 的会话超时可配置，避免内层先炸外层白重试

**测试**：mock 目标函数（成功/失败/超时），状态机流转、心跳、孤儿判定
**验收**：同 spec 两次 fetch 第二次零执行；人为失败后 retry 恢复

### M3 — 首个数据源 tess + 项目 1 实战

**交付**
- `io/sources/tess.py`：`tess_lightcurve(target, sector, cadence)` —— lightkurve 下载
  （缓存重定向 `MAD/cache/lightkurve/`）→ parquet 落 `MAD/tess/<target>/` → 入库
- `io/sources/exoplanet.py`：`exoplanet_params(name)`
- `notebooks/01-tess-transit-wasp12.ipynb`：fetch → 目录周期折叠 → TLS 盲搜 → 对比

**测试**：mock 网络 + fixture parquet
**验收**：notebook 一键出图；断网重跑仍出图（全缓存命中）；DB 可反查完整参数

### M4 — 项目 2 数据源：gaia + asassn

**交付**：`sources/gaia.py`（`gaia_cone`：ADQL → parquet）、`sources/asassn.py`、
`notebooks/02-variable-star.ipynb`（造父变星周期折叠报告）
**验收**：项目 2 跑通；产物可被 lc 层复用

### M5 — aria2 执行器 + 批量：urls + manifest + ztf

**交付**
- `jobs.py` aria2 执行器：JSON-RPC 客户端（addUri/tellStatus/remove），daemon 懒启动，
  `.aria2` 控制文件断点续传
- `io/urls.py`：URL 生成器（先做 ZTF 所需）
- manifest 解析：`submit(manifest.yaml)` 批量建 job
- `sources/ztf.py`：`ztf_meta` / `ztf_cutout` / `ztf_stack`
- `notebooks/03-ztf-mover.ipynb`（项目 3）

**测试**：RPC mock；manifest 单测
**验收（规模压缩至 ≤1GB）**：单天区单波段少量历元完整下载入库；中途 kill aria2c 后
retry 断点续传；失败 URL 状态可见；**顺手实测批量吞吐速率记录在案**
**批量建议夜间跑**（国内访问国际链路慢是常态）

### M6 — TUI：myastro top

**交付**：`io/top.py`（textual）：jobs/storage/datasets 三区块，r/x/enter 交互，孤儿标灰
**验收**：M5 下载活动实时可见；手动删文件后 storage 报缺失

### M7 — 收尾

完整 CLI（fetch/submit/jobs/top/retry）、README 使用手册、依赖锁定

## 网络环境结论（2026-10 实测）

- 11/12 源可达，TTFB 0.8–1.9s；JPL Horizons 连接超时 → 星历改 MPC + skyfield（已入设计文档）
- 生产路径实测：lightkurve 检索 11.3s + 下载 4.4s（WASP-12 TESS S20），小文件场景够用
- 开发迭代不受慢网络影响：单测全 mock，真实网络仅首次冒烟，之后缓存回放

## 约定

- 依赖顺序：M1→M2 严格串行；M3 依 M2；M4 可与 M3 后半并行；M5 依 M2 但量大，M3 实战反馈后再动；M6 依 M5
- 提交粒度：M1/M2 各 2–3 commit，M3+ 每源一 commit，全推 gitea-legacy
- 明确不做（防范围爬升）：限速器、并发调度、其余数据源（panstarrs/unwise/sdss/legacy 按需追加）
