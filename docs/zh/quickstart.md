# 快速上手

从空机器到"这片天区已经是我的了"，五分钟。

## 1. 安装与自检

```bash
pip install myastro
myastro init && myastro doctor
```

## 2. 取一次数据

```python
import myastro as ma

r = ma.fetch("tess", target="WASP-12", sector=20)
print(r.paths[0])          # parquet：time/flux/flux_err/quality
```

再跑一次：第二次**零网络请求**（缓存键 = 规范化的源 + 参数），并且仍能返回原始元数据。

## 3. 查"我已经有什么"

```python
# 精确圆锥检索——坐标在入库时解析
for hit in ma.search(near=(97.6367, 29.6723), radius_deg=0.5):
    print(f"{hit['source']:10s} sep={hit['sep_deg']:.4f}°  {hit['path']}")

# 文本/时间条件可自由组合
ma.search(source="gaia", since="2026-01-01")
```

检索参数会被校验：负半径、赤纬超出 `[-90, 90]`、`limit < 1` 或日期格式错都会显式报错，
而不是静默返回空结果。

## 4. 对全量目录算覆盖率

```bash
myastro index update legacy-bricks     # 36.6 万砖块，约 104MB，只需一次
myastro coverage legacy-bricks
```

```python
ma.coverage("legacy-bricks")   # {'local': n, 'total': 366912, 'ratio': ...}
```

## 5. 校验盘上的文件

```bash
myastro audit        # 首次运行建立 sha256 基线
myastro audit        # 之后报告 缺失 / 尺寸不符 / 损坏
```

## 6. 用 TUI 总览

```bash
myastro top
```

| 按键 | 作用 |
|---|---|
| `0` / `1` / `2` | 数据源 / 作业 / 存储 |
| `enter` | 下钻（存储 → 资产）或展开详情 |
| `F1` / `F2` | 新建下载 / 用选中作业预填表单 |
| `F12` | 批量下单（带索引字段的源） |
| `s` | 切换排序，`f` 循环作业过滤，`x` 取消，`F5` 重试，`F4` 退出 |

## 7. 保住账本

```bash
myastro backup --out ~/myastro-backup     # SQLite 在线备份 + 清单
myastro restore ~/myastro-backup/<时间戳> --force
```

数据文件可以重下，账本（取过什么、用什么参数、sha 基线）不能。请备份它。

## 接下来

- [capabilities.md](dev/capabilities.md)——能力清单与成熟度
- [processing.md](dev/processing.md)——各处理阶段的规则与失败语义
- `notebooks/` 下有端到端示例（输出已清空）
