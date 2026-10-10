# myastro 第二阶段路线图（E 系列）

版本：1.0｜前置文档：[capabilities.md](capabilities.md)（**领域能力清单，最高规划文档**）、[design-io.md](design-io.md)（io 层设计）、[dev-plan.md](dev-plan.md)（第一阶段 M1–M7，已完成）

## 0. 定位与背景

第一阶段交付了 io 层（统一作业基底、双执行器、账本、TUI 雏形）。第二阶段的驱动需求：

1. 执行器（python/aria2）泄漏为用户概念，割裂；python 源无法在 TUI 下单
2. 源完善度不足（TUI 可下单的实际只有 legacy）
3. 只有单文件下载，天文数据的基本形态是批量
4. 本地/云端需要共管：本地不全量持有，但需要时可下载、随时知道本地有什么

**顶层约束（本项目级，非 top 级）**：myastro 是一个库，top 只是 GUI 客户端。
内核必须有良好的公开 API 供第三方调用；讨论以 top 展开时，设计与编码
**不得**局限在 top 视角。

## 1. 分层架构

```
L3 客户端        TUI(top) · CLI · notebook · 第三方程序     ← 平等的四类消费者
L2 API 门面      import myastro → fetch/query/status/…     ← 稳定公开接口
L1 内核          任务注册表(源描述符) · 作业引擎(双执行器) · 账本(db) · 索引
L0 设施适配      aria2 / astroquery / textual              ← 全部可替换
```

第一阶段的问题用这把尺子度量：

- 无门面：内部路径（myastro.io.sources.tess）即事实 API，重构即破坏
- JobSpec 携带 fn 闭包：非数据、不可序列化——CLI/TUI 之外的进程无法凭
  JSON 创建作业；跨进程 retry 因此受限
- 注册表半数据半展示文案：没有按"参数 schema"设计过

## 2. 内核契约：源描述符

内核唯一核心概念，一个抽象服务四个客户端：

```python
@dataclass
class FieldSpec:
    name: str
    type: type            # int/float/str/Enum
    default: Any = None
    label: str = ""       # 展示名（TUI 用，内核不依赖）

class SourceDescriptor:
    name: str
    fields: list[FieldSpec]
    product: str          # 产物格式（TYPES 键）
    def run(self, params: dict) -> JobSpec
```

杠杆点：**一份 fields 声明派生五件事**——TUI 动态表单、CLI 参数
（argparse 自动生成，终结手写命令分发）、参数校验、跨进程持久化
（name+params 即 JSON）、API 参考文档（doc-sync 同思路：文档=渲染产物）。

python 源的 run 产出**具名任务**（TASKS 注册表：名字→顶层函数），
不产闭包——fn 不可序列化的老限制随之消失。

## 3. 架构不变量（测试守卫）

> **top 不得 import 内核私有路径；top 做到的任何事，第三方经由公开门面
> 都能做到。**

守卫方式：测试静态检查 top/ 的 import 只指向门面模块。top 是 API 的
狗粮测试——GUI 用着别扭处即 API 设计缺陷。

## 4. 阶段计划

### E0 门面与契约（最优先，地基）✅ 已完成（0.2.0）

- ✅ FieldSpec / SourceDescriptor 类型化；6 源迁入描述符（包装策略，
  源实现重写留待逐源迁移）
- ✅ 内核任务具名注册（TASKS）；跨进程 python retry 补齐
- ✅ `myastro` 门面包：fetch/query/sources/describe/register_source/
  status/wait/retry/delete/index 系列，`__all__` 即承诺
- ✅ "top 不得导入内核私有符号"守卫测试（首次运行即抓到 _fmt_size 违规）
- ✅ CLI `fetch` 子命令参数从描述符自动生成
- **错误契约**：门面异常体系化（参数错误 / 网络失败 / 数据不存在 /
  状态冲突分类，第三方可 catch 区分）——替代现状散落的异常
- **产物 schema 稳定性**：fetch 返回文件的列 schema（如光变 parquet 的
  time/flux/flux_err/quality）对第三方是契约，列入 `__all__` 同级的
  稳定承诺；变更走版本化（schema_version 字段）

### E1 双执行器隐身（E0 的自然结果）✅ 已完成

- ✅ 执行器从用户视野消失：info 面板执行器列移除（详情保留通道说明）
- ✅ TUI 新建表单全源通用（描述符驱动）：tess/gaia/ztf-meta（python 任务）
  与 ztf/legacy/unwise（URL 构造）同一下单表单；FieldSpec 补 optional 语义
- ✅ 表单预览对 python 源显示"任务+参数+产物"，URL 源显示"URL+落盘路径"——
  预览文本本身不再出现执行器字样

### E2 源完善（可与 E1 后半并行）

| 优先级 | 源 | 状态 |
|---|---|---|
| 高 | mpc、simbad、vizier | ✅ 已实现（E2 首批；simbad 有低概率原生段错误，
  单次重试恢复，note 已记） |
| 高 | skyfield | 待做：DE440s 历表本地化（jpl.nasa.gov 不可达，需找镜像） |
| 中 | panstarrs | 受阻：ps1catalog 端点已迁移（404），需考古新 API |
| 用户动作 | ztf 全面解锁 | **等用户注册 IRSA token** |
| 待恢复 | asassn、unwise | 定期重试；实现已就位 |

### E3 批量下载 ✅ 已完成

- ✅ jobs 表 `batch_id`（migration v4）+ `jobs.submit_batch` + 门面
  `ma.batch(source, param_rows)` + `ma.status(batch_id=...)`
- ✅ TUI 批量下单屏（`b` 键）：源选择 → 前缀过滤（上限 300 渲染）→
  SelectionList 多选（空格勾选）→ Ctrl+S 整批提交；实测批次 b21a301cd 走通
- ✅ 传输并发由 aria2 原生承担

### E4 本地/云端共管视图（部分随 E3 提前交付）

先划边界：**"随时知道云端有什么"不存在全局解**（云端全集无限大）。
正确模型：

```
云端认知 = 每源可枚举目录（索引：brick 366k、field 列表…）
本地事实 = astro.db 账本
共管视图 = 索引 × 账本 join：条目 → ✓ 已有 / ☁ 仅云端（可一键下）
```

- ✅ 批量下单屏的选项标签已带 ✓本地/☁云端 标记（E3 顺带交付）
- ✅ "需要时下载" = 在同一屏勾选 ☁ 条目 Ctrl+S（按需下载即达成）
- ✅ 覆盖率统计（本地/全量）：`ma.coverage(index)` + CLI `myastro coverage`，实测 legacy-bricks 7/366912
- 不可枚举源（gaia/ztf 查询型）的云端认知仍走查询 API = notebook 领地，
  TUI 不做网络检索的边界不变

## 5. 稳定性与依赖策略

- `myastro.__version__` 语义化版本；门面符号改动走 deprecation
- io/ 以下内核私有，重构自由
- 不引入 pydantic/click/typer：FieldSpec 用 dataclass 手写（零多余依赖），
  CLI 生成与描述符合一，功能重复的轮子不装
- io 层作为整合层有存在正当性（查询=astroquery、传输=aria2、UI=textual
  各司其职；DVC/git-lfs 类工具不适用——云端是异构公共档案非单一 remote）

## 6. 纪律（延续第一阶段）

测试全绿才提交 · 注册表声明式扩展 · 身份寻址 · 文档=渲染产物
（doc-sync 纳入新注册表）· 每阶段结束做一次架构 review（对照本文档）。
