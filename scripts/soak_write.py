#!/usr/bin/env python
"""浸泡测试：反复跑"取数 → 写 parquet"路径，统计进程崩溃率。

为什么需要它：实测在工作线程里写 parquet 偶发段错误（崩溃点
`pyarrow.parquet.ParquetWriter.__init__`），频率低到单次测试抓不住，而段错误会
直接杀掉 pytest 进程——所以只能这样在**子进程**里反复跑、统计退出码。

用法：
    python scripts/soak_write.py [次数] [--python /path/to/python]

退出码：0 = 全部通过；1 = 有崩溃（会打印崩溃日志路径）。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile

CASE = """
import myastro as ma
ma.fetch('ztf-lc', ra=270.0, dec=30.0, radius_arcsec=5.0)
ma.fetch('ztf-meta', field=673, filtercode='zr', ccdid=1, qid=1,
         jd_min=2458696.5, jd_max=2458698.5)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="?", type=int, default=20)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    crashes, errors = [], []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="soak-"))
    for i in range(args.runs):
        env = {"HOME": str(tmp / "home"), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
               "MYASTRO_DATA": str(tmp / "data"), "MYASTRO_DB": str(tmp / "astro.db")}
        (tmp / "home").mkdir(exist_ok=True)
        p = subprocess.run([args.python, "-u", "-c", CASE], env=env,
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            log = tmp / f"crash-{i}.log"
            log.write_text(p.stdout + p.stderr)
            # 区分**崩溃**（被信号杀掉：returncode < 0 / 139）与普通异常
            # （网络不通、服务 5xx 等）：后者不是我们在查的东西，否则 CI 会被
            # IRSA 的可用性搞红。
            if p.returncode < 0 or p.returncode >= 128:
                crashes.append((i, p.returncode, log))
                print(f"  第 {i + 1} 次：**崩溃**（退出码 {p.returncode}）→ {log}")
            else:
                errors.append((i, p.returncode, log))
                print(f"  第 {i + 1} 次：普通失败（退出码 {p.returncode}，多为网络）")
        else:
            print(f"  第 {i + 1} 次：通过")
    rate = len(crashes) / max(args.runs, 1)
    print(f"\n{args.runs} 次中崩溃 {len(crashes)} 次（{rate:.0%}）")
    if errors:
        print(f"（另有 {len(errors)} 次普通失败，与崩溃无关，通常是网络/服务不可用）")
    if crashes:
        print("崩溃栈（第一次）：")
        print(crashes[0][2].read_text()[:1500])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
