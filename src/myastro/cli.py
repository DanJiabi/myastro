"""CLI 入口：myastro <子命令>。每命令一个处理函数，main 负责分发与错误→退出码。"""
from __future__ import annotations

import argparse
import sys

from .io import jobs
from .io.db import DB


def _cmd_jobs(args, db) -> int:
    import myastro as ma

    rows = ma.status()
    if not rows:
        print("（无作业）")
    for r in rows:
        err = f"  err={r['error'][:60]}" if r.get("error") else ""
        print(f"#{r['id']:<4} {r['executor']:<7} {r['status']:<10}"
              f" {r['updated_at']}{err}")
    return 0


def _cmd_wait(args, db) -> int:
    import myastro as ma

    result = ma.wait(args.job_id)
    for p in result.paths:
        print(p)
    return 0


def _cmd_retry(args, db) -> int:
    import myastro as ma

    ma.retry(args.job_id)
    print(f"job {args.job_id} 已重新提交")
    return 0


def _cmd_delete(args, db) -> int:
    import myastro as ma

    out = ma.delete(args.job_ids)
    if out["deleted"]:
        print(f"已删除 {len(out['deleted'])}: {out['deleted']}"
              f"（dataset/files 资产保留）")
    for job_id, reason in out["refused"]:
        print(f"拒绝 job {job_id}: {reason}")
    return 0 if not out["refused"] else 1


def _cmd_orphans(args, db) -> int:
    n = jobs.find_orphans(db=db)
    print(f"标记孤儿作业 {n} 个")
    return 0


def _cmd_index(args, db) -> int:
    import myastro as ma

    if args.index_cmd == "list":
        for r in ma.index_list():
            print(f"{r['name']:<16} "
                  f"{'已构建' if r['built'] else '未构建'}  {r['desc']}")
    else:
        print(f"索引已更新: {ma.index_update(args.name)}")
    return 0


def _cmd_fetch(args, db) -> int:
    import myastro as ma
    params = {k: v for k, v in vars(args).items()
              if k not in ("fn", "cmd", "source") and v is not None}
    r = ma.fetch(args.source, **params)
    for p in r.paths:
        print(p, f"(cache_hit={r.cache_hit})")
    return 0


def _cmd_audit(args, db) -> int:
    import myastro as ma
    r = ma.audit()
    print(f"核对 {r['total']}：ok {r['ok']} | 基线新建 {r['baselined']} | "
          f"缺失 {r['missing']} | 尺寸不符 {r['size_mismatch']} | "
          f"损坏 {r['corrupt']}")
    for kind in ("missing", "size_mismatch", "corrupt"):
        for item in (__import__("myastro.io.integrity", fromlist=["x"])
                     .audit_detail(kind, limit=10)):
            print(f"  [{kind}] {item['path']} ({item['why']})")
    return 0 if (r["missing"] + r["size_mismatch"] + r["corrupt"]) == 0 else 1


def _cmd_search(args, db) -> int:
    import myastro as ma
    near = tuple(args.near) if args.near else None
    rows = ma.search(source=args.source, target=args.target,
                     name=args.name, since=args.since, until=args.until,
                     near=near, radius_deg=args.radius)
    for r in rows:
        sep = f" sep={r['sep_deg']:.4f}°" if "sep_deg" in r else ""
        print(f"#{r['id']:<3} {r['source']:<10} {r['target'] or '-':<14}"
              f"{sep} {r['created']}  {r['path'] or ''}")
    print(f"共 {len(rows)} 条")
    return 0


def _cmd_coverage(args, db) -> int:
    import myastro as ma
    r = ma.coverage(args.index)
    print(f"{r['index']}: 本地 {r['local']} / 全量 {r['total']}"
          f"（{r['pct']}%）")
    return 0


def _cmd_retry_batch(args, db) -> int:
    import myastro as ma
    out = ma.retry_batch(args.batch_id)
    print(f"重试 {len(out['retried'])}: {out['retried']}")
    for jid, why in out["skipped"]:
        print(f"  跳过 {jid}: {why}")
    return 0


def _cmd_test_map(args, db) -> int:
    from .errors import ParamError

    try:
        return _test_map(args)
    except ValueError as e:          # 不在源码仓库（如已安装的 wheel）
        raise ParamError(f"该命令仅用于源码仓库：{e}") from e


def _test_map(args) -> int:
    from .io.testmap import problems, sync
    if args.check:
        issues = problems()
        for i in issues:
            print("✗", i)
        print("测试能力地图：", "一致" if not issues else f"{len(issues)} 处不一致")
        return 1 if issues else 0
    path = sync()
    print(f"已生成 {path}")
    for i in problems():
        print("  ⚠", i)
    return 0


def _cmd_health(args, db) -> int:
    import myastro as ma
    for r in ma.health(args.source):
        mark = {"ok": "✅", "degraded": "⚠", "unreachable": "❌"}.get(
            r["status"], "?")
        print(f"{mark} {r['source']:<10} {r['status']:<12} {r['detail']}")
    return 0


def _cmd_schedule(args, db) -> int:
    import myastro as ma

    from .io.schedule import remove
    if args.schedule_cmd == "list":
        for r in ma.schedule_list():
            mark = "✅已装" if r["installed"] else "—未装"
            print(f"{mark} {r['task']:<13} {r['when']}  {r['desc']}")
    elif args.schedule_cmd == "install":
        p = ma.schedule_install(args.task)
        print(f"已安装 launchd 任务: {p}")
    else:
        print("已移除" if remove(args.task) else "本就未安装")
    return 0


def _cmd_docsync(args, db) -> int:
    from .errors import ParamError
    from .io.docsync import sync

    try:
        print("文档已更新" if sync() else "文档已是最新（无变化）")
    except ValueError as e:          # 不在源码仓库（如已安装的 wheel）
        raise ParamError(f"该命令仅用于源码仓库：{e}") from e
    return 0


def _cmd_init(args, db) -> int:
    import myastro as ma

    paths = ma.init_root()
    print("数据根:", paths["data"])
    print("缓存:  ", paths["cache"])
    print("账本:  ", paths["db"])
    return 0


def _cmd_doctor(args, db) -> int:
    import myastro as ma

    checks = ma.doctor()
    symbol = {"ok": "✓", "warn": "⚠", "fail": "✗"}
    for c in checks:
        line = f"{symbol.get(c['status'], '?')} {c['name']}"
        if c["detail"]:
            line += f"：{c['detail']}"
        print(line)
        if c["fix"] and c["status"] != "ok":
            print(f"    → {c['fix']}")
    fails = sum(1 for c in checks if c["status"] == "fail")
    warns = sum(1 for c in checks if c["status"] == "warn")
    print(f"自检完成：{len(checks)} 项，{warns} 个警告，{fails} 个问题")
    return 1 if fails else 0


def _cmd_backup(args, db) -> int:
    import myastro as ma

    out = ma.backup(args.out, with_index=args.with_index)
    print(f"备份目录: {out['dir']}")
    print(f"账本:     {out['db']}（{out['bytes'] / 1024:.0f} KB）")
    print(f"清单:     {out['manifest']}")
    if out["with_index"]:
        print("（含索引副本）")
    return 0


def _cmd_restore(args, db) -> int:
    import myastro as ma

    out = ma.restore(args.source, force=args.force)
    print(f"已从 {out['restored_from']} 恢复 → {out['db']}")
    if out["safety_copy"]:
        print(f"覆盖前的账本已留存: {out['safety_copy']}")
    print(f"计数: {out['counts']}")
    return 0


def _cmd_top(args, db) -> int:
    from .io.top import AstroTop
    AstroTop().run()
    return 0


def _add_fetch(parser: argparse.ArgumentParser) -> None:
    """fetch 子命令：参数由源描述符的 FieldSpec 声明生成。"""
    from .descriptors import REGISTRY
    sub = parser.add_subparsers(dest="source", required=True,
                                metavar="SOURCE")
    for name, d in REGISTRY.items():
        p = sub.add_parser(name, help=d.desc)
        for f in d.fields:
            extra = {}
            if f.choices:
                extra["choices"] = f.choices
            p.add_argument(f"--{f.name.replace('_', '-')}",
                           dest=f.name,
                           default=f.default,
                           type=str if f.type is str else f.type,
                           help=f.label or None, **extra)
        p.set_defaults(fn=_cmd_fetch)


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(prog="myastro",
                                     description="天文数据获取与管理")
    # --version（版本单一来源见 src/myastro/__init__.py::_detect_version）
    parser.add_argument("--version", action="version",
                        version=f"myastro {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("jobs", help="列出作业（最近 100 条）").set_defaults(
        fn=_cmd_jobs)
    p_wait = sub.add_parser("wait", help="阻塞等待作业完成")
    p_wait.add_argument("job_id", type=int)
    p_wait.set_defaults(fn=_cmd_wait)
    p_retry = sub.add_parser("retry", help="重试失败/僵尸/done(force)作业")
    p_retry.add_argument("job_id", type=int)
    p_retry.set_defaults(fn=_cmd_retry)
    p_fetch = sub.add_parser("fetch", help="获取数据（参数由描述符生成）")
    _add_fetch(p_fetch)
    p_sched = sub.add_parser("schedule", help="定时任务（launchd）管理")
    sc = p_sched.add_subparsers(dest="schedule_cmd", required=True)
    sc.add_parser("list", help="列出任务与安装状态")
    p_si = sc.add_parser("install", help="安装 launchd 任务")
    p_si.add_argument("task", choices=list(
        __import__("myastro.io.schedule", fromlist=["TASKS"]).TASKS))
    p_sr = sc.add_parser("remove", help="移除任务")
    p_sr.add_argument("task", choices=list(
        __import__("myastro.io.schedule", fromlist=["TASKS"]).TASKS))
    p_sched.set_defaults(fn=_cmd_schedule)
    sub.add_parser("init", help="创建数据根与账本（幂等）").set_defaults(
        fn=_cmd_init)
    sub.add_parser("doctor", help="环境自检（依赖/路径/账本/索引/平台）").set_defaults(
        fn=_cmd_doctor)
    p_bk = sub.add_parser("backup", help="备份账本（SQLite 在线备份）")
    p_bk.add_argument("--out", help="备份输出目录（默认 账本目录/backups/时间戳）")
    p_bk.add_argument("--with-index", action="store_true", dest="with_index",
                      help="连同索引 parquet 一起复制（可上百 MB）")
    p_bk.set_defaults(fn=_cmd_backup)
    p_rs = sub.add_parser("restore", help="从备份恢复账本（默认拒绝覆盖）")
    p_rs.add_argument("source", help="备份目录或 astro.db 路径")
    p_rs.add_argument("--force", action="store_true",
                      help="覆盖现有账本（会先留存 .pre-restore-*.bak）")
    p_rs.set_defaults(fn=_cmd_restore)
    p_tmap = sub.add_parser("test-map", help="生成/检查测试能力地图")
    p_tmap.add_argument("--check", action="store_true",
                        help="只检查不写文件（守卫用）")
    p_tmap.set_defaults(fn=_cmd_test_map)
    p_health = sub.add_parser("health", help="源健康探测")
    p_health.add_argument("source", nargs="?", default=None)
    p_health.set_defaults(fn=_cmd_health)
    p_audit = sub.add_parser("audit", help="完整性巡检（sha 基线+核对）")
    p_audit.set_defaults(fn=_cmd_audit)
    p_search = sub.add_parser("search", help="本地检索已有数据")
    p_search.add_argument("--source"); p_search.add_argument("--target")
    p_search.add_argument("--name"); p_search.add_argument("--since")
    p_search.add_argument("--until")
    p_search.add_argument("--near", nargs=2, type=float, metavar=("RA", "DEC"),
                          help="精确圆锥检索中心（度）")
    p_search.add_argument("--radius", type=float, default=0.1,
                          help="圆锥半径（度，默认 0.1）")
    p_search.set_defaults(fn=_cmd_search)
    p_cov = sub.add_parser("coverage", help="索引覆盖率")
    p_cov.add_argument("index")
    p_cov.set_defaults(fn=_cmd_coverage)
    p_rb = sub.add_parser("retry-batch", help="整批重试失败作业")
    p_rb.add_argument("batch_id")
    p_rb.set_defaults(fn=_cmd_retry_batch)
    p_del = sub.add_parser("delete", help="删除作业记录（资产保留）")
    p_del.add_argument("job_ids", nargs="+", type=int)
    p_del.set_defaults(fn=_cmd_delete)
    sub.add_parser("orphans", help="扫描并标记心跳超时的孤儿作业"
                    ).set_defaults(fn=_cmd_orphans)

    p_idx = sub.add_parser("index", help="本地索引管理（TUI 候选列表）")
    p_idx_sub = p_idx.add_subparsers(dest="index_cmd", required=True)
    p_idx_sub.add_parser("list", help="列出索引").set_defaults(fn=_cmd_index)
    p_upd = p_idx_sub.add_parser("update", help="强制更新（下载→解析→删源）")
    p_upd.add_argument("name")
    p_upd.set_defaults(fn=_cmd_index)

    sub.add_parser("doc-sync",
                   help="再生 design-io.md 数据源矩阵（文档=渲染产物）"
                   ).set_defaults(fn=_cmd_docsync)
    sub.add_parser("top", help="数据管理 TUI").set_defaults(fn=_cmd_top)
    return parser


# 退出码契约（脚本可据此分流；错误消息走 stderr，不打印栈）：
#   0 成功 | 1 部分失败（如删除时部分作业被拒绝）| 2 参数错 | 3 未找到
#   | 4 网络 | 5 状态不允许 | 130 键盘中断
EXIT_CODES = {
    "ParamError": 2,        # 参数/未知源：调用方传错了
    "NotFoundError": 3,     # 目标不存在（作业/索引/批次）
    "NetworkError": 4,      # 网络侧失败（重试后）
    "StateError": 5,        # 状态不允许（如 done 重试、健康作业删除）
}


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：异常转成清晰的 stderr 消息 + 退出码。

    早期版本没有这一层——`myastro retry 999999` 直接抛栈崩溃。
    对"第三个客户端"（脚本/第三方）而言，退出码是可编程契约的一部分。
    """
    from . import errors

    args = _build_parser().parse_args(argv)
    if args.cmd == "top":
        try:
            return args.fn(args, None)
        except KeyboardInterrupt:
            print("已中断", file=sys.stderr)
            return 130
    db = DB().init()                     # 单连接：用完即关（不再每命令各开一个）
    try:
        return args.fn(args, db)
    except errors.ParamError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        return EXIT_CODES["ParamError"]
    except errors.NotFoundError as e:
        print(f"未找到：{e}", file=sys.stderr)
        return EXIT_CODES["NotFoundError"]
    except errors.NetworkError as e:
        print(f"网络错误：{e}", file=sys.stderr)
        return EXIT_CODES["NetworkError"]
    except errors.StateError as e:
        print(f"状态不允许：{e}", file=sys.stderr)
        return EXIT_CODES["StateError"]
    except LookupError as e:            # 内核侧"不存在"（如未知任务/索引）
        print(f"未找到：{e}", file=sys.stderr)
        return EXIT_CODES["NotFoundError"]
    except ValueError as e:             # 内核侧参数问题
        print(f"参数错误：{e}", file=sys.stderr)
        return EXIT_CODES["ParamError"]
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
