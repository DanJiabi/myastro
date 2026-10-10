# myastro.io 设计文档

版本：1.0（定稿）｜状态：已评审收敛｜后续：[roadmap-e.md](roadmap-e.md)（E0–E4）

## 1. 目标与边界

把"下载天文数据"变成可信赖的本地操作：**幂等**（同参数重复调用不重复下载）、**可追溯**（每次数据从哪来、什么参数）、**可复现**（任何图能反查出数据来源）。

不造的轮子：

- 不实现任何下载协议与查询语言——委托 astroquery / lightkurve / ztfquery / pyvo / aria2c
- 不管数据格式转换——属 lc / imaging / phot 层
- TB 级批量归档也纳入管理（作为 job），但传输由 aria2c 承担

## 2. 关键设计决策

- 一切网络获取统一为 job；`fetch()` 只是 submit + wait 的语法糖，缓存命中不产生 job（未碰网络）。
  （曾考虑按数据类型三分、按体积阈值二分：类型与体积正交，Gaia 锥查等案例跨档；体积阈值依赖网络环境。均否决。）
- 双执行器：python（寄生调用方进程，心跳自报）/ aria2（RPC daemon，后台存活）。
  lightkurve 等包内部自带 HTTP 会话，无法整体改走 aria2，故不统一传输层。
- 无中心化后台服务；TUI 直接读 DB + aria2 RPC。
  执行基座异构（aria2 daemon + 各调用方进程），TUI 是统一观察面。

## 3. 总体结构

```
调用侧                              观察侧
fetch(spec) = submit + wait          myastro top（TUI, textual）
submit(manifest)                      ├─ jobs：live(aria2 RPC) + DB + 心跳/孤儿
  │                                   ├─ storage：DB + 目录实扫核对
  ▼                                   └─ datasets：参数钻取
jobs.py 双执行器
  ├─ python：寄生调用方进程，心跳自报
  └─ aria2：RPC daemon，后台存活
        ▼
   astro.db（datasets / files / jobs）
```

**后台存活性**（文档级约定）：

- aria2 执行器：调用方死了也活着，重启无损（aria2 控制文件）
- python 执行器：调用方活着才活着；心跳超时 → TUI 标 orphaned → retry 重新提交

## 4. 目录布局

```
~/myastro-data/                  # data root（可放网络盘），MYASTRO_DATA 可覆盖
├── cache/                       # 第三方包自身缓存（lightkurve/astropy 重定向目标）
└── <mission>/<target>/          # 我们管理的资产，按源/目标分

~/.local/state/myastro/astro.db  # 元数据库：本地盘
```

**重要**：astro.db 不放 NFS。SQLite 锁与 WAL 共享内存在 NFS 上不可靠（官方警告，
症状为随机 database is locked 或静默损坏）。数据文件（顺序读写）在 NFS 无碍。
配置项：`MYASTRO_DATA`（默认 `~/myastro-data`）、`MYASTRO_DB`（默认 `~/.local/state/myastro/astro.db`）。

## 5. 数据库 schema（v8）

```sql
datasets  (id, source, target, params_json, cache_key UNIQUE, created_at,
           status, meta_json,            -- v6：溯源 meta（缓存命中可回读）
           ra, dec)                      -- v8：入库时解析的坐标 + 位置索引
files     (id, dataset_id, path UNIQUE, size, sha256, remote_url,
           fetched_at, format)
jobs      (id, spec_json, executor 'python'|'aria2', url, dest,
           status 'queued'|'running'|'verifying'|'done'|'failed'|'orphaned',
           progress, speed, error, updated_at,   -- updated_at 兼作心跳
           started_at, finished_at, file_id, dataset_id,   -- v2
           gid,                                  -- v3：aria2 句柄
           batch_id,                             -- v4：批次单元
           error_type)                           -- v7：失败类型（异常类名）
health    (source PRIMARY KEY, status, detail, checked_at)     -- v5
```

- `datasets.params_json`：可复现性核心，记录全部查询参数
- 迁移 v1→v8 逐版追加（`_MIGRATIONS`）；**已发布的迁移不得修改**——
  改历史迁移会让"新库"与"升级库"分叉（真实踩坑：把新列写进 v1 建表语句，
  新库再跑 ALTER 直接 duplicate column）
- 建表语句与迁移路径的一致性由 `tests/kernel/test_db.py::`
  `test_fresh_schema_covers_all_code_columns` 守卫
- **各字段的处理语义**（何时写、失败怎么办）见 [processing.md](processing.md) §3/§4

## 5.1 路径不变量（2026-10-10 加）

**任何落盘产物必须在数据根之下。** 两道防线：
1. 输入即拒——会把参数拼进文件名/目录名的字段声明 `FieldSpec.name_like`（走
   `io/core.py::safe_name`）或 `pattern`（如 `brick` 的 8 位格式）；
2. 运行时兜底——`jobs/store.py::_assert_paths_inside_data_root` 在写库**之前**
   校验任务返回的每个路径，覆盖"新源忘了标注"的情况。

背景：此前靠各处自行处理（tess 的 slug 挡不住 `..`、mpc 只换空格、legacy 完全没处理），
`brick="../../x"` 实测能把产物写到数据根之外。

## 6. 核心组件（现状）

| 模块 | 职责 |
|---|---|
| `core.py` | 重试（指数退避 1→60s×5，仅 5xx/网络错）、原子落盘、缓存键规范化 |
| `config.py` | 数据根/DB 路径（`MYASTRO_DATA`/`MYASTRO_DB`）、目录初始化 |
| `db.py` | schema + 迁移（v1→v8） |
| `jobs/` | 作业基底的包：`spec`（契约/会话）、`store`（落库与缓存）、`rebuild`（历史行→spec）、`aria2_exec`（aria2 收账）、`runner`（python 执行/提交/fetch）、`lifecycle`（僵尸/重试/删除/批次）、`query`（状态/等待） |
| `coords.py` | 坐标解析（params→meta→源 resolver→文件名兜底）与角距计算 |
| `index.py` | 本地索引：两类来源、进程内缓存、bisect 前缀查询、精确键查询 |
| `search.py` | 本地检索：源/目标/文件名/时间 + 精确圆锥坐标检索 |
| `integrity.py` | 完整性巡检：sha 基线、损坏/缺失检测 |
| `health.py` | 源健康探测（判级 + 落库 + 面板覆盖） |
| `schedule.py` | 定时任务（launchd 代理生成/装卸） |
| `testmap.py` | 测试能力地图生成（能力 → 测试） |
| `sources/` | 每源一模块：网络层 + 落盘 + 入库（`_fn` 供任务注册） |
| `urls.py` | aria2 型源的 URL/文件名派生（manifest 与 legacy/ztf 共用） |
| `top/` | TUI（panes/screens/batchscreen/suggest/app），详见 [design-top.md](design-top.md) |

> 每个环节的**处理规则与失败语义**见 [processing.md](processing.md)。

## 7. 支持的数据源与实现方式

### 7.1 矩阵总览

> **已实现清单的权威出处 = `io/sources/__init__.py` 的 SOURCES 注册表**
> （TUI info 面板即读它）。本矩阵是规划全集，状态列标注实现情况。

<!-- BEGIN sources-matrix -->
| 数据源 | 说明 | 状态 | 执行器 | 通道 | 产物 | TUI 下单 |
|---|---|---|---|---|---|---|
| tess | TESS/Kepler/K2 光变曲线 → parquet | ✅ 可用 | python · lightkurve | lightkurve | parquet | — |
| exoplanet | NASA Exoplanet Archive 凌星参数直查 | ✅ 可用 | python · astroquery.nexsci | astroquery.nexsci | dict | — |
| gaia | Gaia DR3 锥形星表切片 → parquet | ✅ 可用 | python · astroquery.gaia (ADQL) | astroquery.gaia (ADQL) | parquet | — |
| asassn | ASAS-SN Sky Patrol v2 变星光变 | ❌ 不可达 | python · pyasassn | pyasassn | parquet | — |
| ztf-meta | ZTF sci 帧元数据（视宁度/历元）→ parquet | ✅ 可用 | python · ibe HTTP | ibe HTTP | parquet | — |
| ztf | ZTF sci 图像单帧/多帧栈下载 | ✅ 可用 | aria2 · ibe HTTP | ibe HTTP | fits | ztf |
| legacy | Legacy Surveys DR10 tractor 星表（brick 切片） | ✅ 可用 | aria2 · NERSC HTTP | NERSC HTTP | fits | legacy |
| unwise | unWISE 中红外叠加切片 | ✅ 可用 | python · unwise.me cutout（requests + tarfile） | unwise.me cutout（requests + tarfile） | fits（含辅助） | — |
| manifest | 任意 URL 批量下载（manifest 提交） | ✅ 可用 | aria2 · yaml 清单 | yaml 清单 | 任意 | — |
| mpc | MPC 小行星/彗星星历（Horizons 替代） | ✅ 可用 | python · astroquery.mpc | astroquery.mpc | parquet | — |
| simbad | SIMBAD 锥搜：天区目标认证 | ✅ 可用 | python · astroquery.simbad | astroquery.simbad | parquet | — |
| vizier | VizieR 任意发表星表锥检 | ✅ 可用 | python · astroquery.vizier | astroquery.vizier | parquet | — |
| ztf-lc | ZTF 光变曲线（IRSA 凭据） | ✅ 可用 | python · ztfquery.lightcurve | ztfquery.lightcurve | parquet | — |
| horizons | JPL Horizons 星历 | ❌ 不可达 | python · — | — | — | — |
| （规划未实现，3 项） | | | | | | |
| panstarrs | Pan-STARRS DR2 stack cutout（MAST URL） | 未实现 | — | — | — | — |
| sdss | SDSS DR18 光谱/测光（astroquery.sdss） | 未实现 | — | — | — | — |
| skyfield | DE440s 历表本地化（一次性下载） | 未实现 | — | — | — | — |
<!-- END sources-matrix -->

### 7.2 逐源实现要点

**tess.py** — `tess_lightcurve(target, sector=None, cadence='2m')`
lightkurve `search_lightcurve` → 选扇区 → 下载（其缓存重定向到 `cache/lightkurve/`）→ 转 parquet 存 `data/tess/<target>/` → 入库。params_json 记 target/sector/cadence/PDCSAP 版本。项目 1 主入口。

**exoplanet.py** — `exoplanet_params(name)`
NexSci Archive 查行星参数（周期、深度、T0），供折叠与 TLS 对比。量级 KB，纯查表。

**gaia.py** — `gaia_cone(coord, radius, columns)`
`astroquery.gaia` 同步 ADQL（小锥）或异步 job（大锥，Gaia 侧 TAP 异步，与我们的 job 模型两层，注意区分文档措辞）。产物 parquet。参考星选取/交叉匹配的基础。

**asassn.py** — `asassn_lightcurve(target)` / `asassn_bulk(targets_file)`
Sky Patrol v2 API。单目标走 python 执行器；成批目标（万级）导出为 URL 列表交 aria2。项目 2 主入口。

**ztf.py** — `ztf_meta(coord, radius)` / `ztf_cutout(...)` / `ztf_stack(field, band, jd_range)`
元数据与单帧 cutout 走 ztfquery（IRSA）；多历元整栈（每帧 ~100MB，单天区 5–10GB）由 ztfquery 拿到 URL 后交 aria2 执行器。**项目 3 主入口，最复杂，最后实现。**

**panstarrs.py** — `panstarrs_cutout(coord, size, band)`
MAST PS1 cutout 服务返回直接 URL → aria2。参考图像与对照星来源。

**unwise.py** — `unwise_cutout(coord, band)`
unwise.me 切片 URL 生成 → aria2。红外波段补充。

**mpc.py** — `mpc_orbit(target)` / `mpc_ephemeris(target, epochs)`
astroquery.mpc + MPC Ephemeris API。项目 3 小行星星历交叉验证；未来 N.I.N.A 目标规划复用。
**注意**：原方案的 JPL Horizons（ssd.jpl.nasa.gov）经实测从本网络连接超时不可达，
故星历以 MPC API + skyfield 本地计算（DE440s 历表一次性下载后离线）双路实现，
Horizons 仅作为网络可达时的可选后备。2026-10 实测各源连通性：除 Horizons 外全部可达，TTFB 0.8–1.9s。

**simbad.py / vizier.py** —薄封装 astroquery 对应模块，目标认证与临时拉取任意星表。

**sdss.py** — `sdss_spec(coords)`
astroquery.sdss，光谱 lite 文件。可选练手。

**legacy.py（urls.py 生成器）** — `legacy_tractor_tile(ra_hi)` / `legacy_coadd_tile(tile)`
按 tile 命名规则生成 tractor 星表与 coadd 图 URL，manifest + aria2 批量拉。URL 生成器是免手写 URL 的关键。

**skyfield 历表** — 首次使用自动下载 DE440s（~35MB）到 data root，之后永久缓存。

### 7.3 各源公共约定

- spec 必含：source、params（全参数）、executor、size_hint、dest 模板
- 缓存键 = (source, params_json 规范化哈希)；命中即返回，不产生 job
- 限流从宽到严：MAST 正常、IRSA 保守（ztfquery 自带节流配置，透传）
- 凭据：数据本身均为公开档；**IRSA（ZTF 元数据/图像）在本机配置了账号以提高配额**，ztf-lc 的原生 API 不需要凭据（匿名配额是否够用未实测）

## 8. TUI（`myastro top`）

见 [design-top.md](design-top.md)（单一出处，避免两处维护）：
三面板 0 数据源 / 1 作业 / 2 存储，模态 F1 新建 / F2 预填充 / F12 批量，
字段标签 + 原生 suggester 补全（→ 接受），身份寻址的光标/详情契约。

## 9. 测试与验收

分层与纪律见 [testing.md](testing.md)，能力→测试映射见 [test-map.md](test-map.md)。
现状：240+ 用例，六层（unit/kernel/sources/facade/ui/guards），全量离线可跑；
push 前由 `githooks/pre-push` 跑全量门（pytest + pyflakes）。

第一阶段的三条验收（同参数两次只产生一次网络请求；断网重试可恢复；
删文件后库能报告缺失）已由内核层测试长期守着。

## 10. 实施顺序（第一阶段历史记录，已完成）

1. core.py + db.py
2. sources/tess.py（项目 1 急用，python 执行器路径打通）
3. gaia.py、asassn.py（项目 2）
4. jobs.py aria2 执行器 + urls.py + ztf.py（项目 3，批量场景真实出现时）
5. top.py（TUI，有了真实下载活动才有意义）

每步都是"要用的先写"，不预建没人用的部件。
