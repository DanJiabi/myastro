# myastro-source-example

一个**完全离线**的 myastro 插件示例：`demo` 源生成合成正弦光变并落盘。
它演示 `docs/plugin-api.md` 里的协议 v1 全部要点（按名注册的任务、描述符、校验、
统一落盘、入账本）。

## 安装与试跑

```bash
pip install -e examples/myastro-source-example

python - <<'PY'
# 不需要 import 插件：entry-points 自动发现（0.5.0 起）
import myastro as ma

print("源列表可见:", "demo" in {s["name"] for s in ma.sources()})
r = ma.fetch("demo", target="M31")
print("落盘:", r.paths[0], "| dataset_id:", r.dataset_id)
print("可检索:", bool(ma.search(source="demo")))
PY
```

CLI 同样可用（发现是自动的）：

```bash
myastro fetch demo --target M31
```

## 这个示例刻意演示的约束

- 只用公开 API（`import myastro as ma`），不碰 `myastro.io.*`；
- 任务**按名注册**（`JobSpec` 只存名字，重试与跨进程恢复依赖它）；
- 进文件名的字段必须声明 `pattern`（协议强制，防路径穿越）；
- 落盘走 `ma.write_parquet`（原子替换 + pyarrow 线程规避），且写在 `ctx.dest_dir` 内。

## CI

主仓库的 CI 会安装本示例并**真取一次**（断言文件落盘 + 账本可检索），
见 `.github/workflows/ci.yml` 的 "Example plugin (batch 3)" 步骤。
