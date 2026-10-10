"""定时任务：生成并管理 macOS launchd 代理（capabilities §2 schedule）。

轮子检查：调度不自建——launchd 负责"何时跑"，myastro 只提供
"跑什么"（CLI 子命令）与任务定义的生成/装卸。

任务清单（v1）：
  health          每日 09:00  myastro health（源探测 + 落库）
  index-weekly    每周日 03:00 myastro index update legacy-bricks
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"

TASKS: dict[str, dict] = {
    "health": {
        "label": "com.myastro.health",
        "argv": [sys.executable, "-m", "myastro", "health"],
        "hour": 9, "minute": 0, "weekday": None,
        "desc": "每日源健康探测（结果落库，info 面板自动覆盖显示）",
    },
    "index-weekly": {
        "label": "com.myastro.index",
        "argv": [sys.executable, "-m", "myastro", "index",
                 "update", "legacy-bricks"],
        "hour": 3, "minute": 0, "weekday": 0,      # 周日
        "desc": "每周日 03:00 刷新 legacy-bricks 索引（104MB，夜间）",
    },
}


def _plist(task: str) -> Path:
    return LAUNCHD_DIR / f"{TASKS[task]['label']}.plist"


def _render(task: str) -> str:
    t = TASKS[task]
    when = (f"<key>Weekday</key><integer>{t['weekday']}</integer>"
            if t["weekday"] is not None else "")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{t['label']}</string>
    <key>ProgramArguments</key>
    <array>
{chr(10).join(f"        <string>{a}</string>" for a in t['argv'])}
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        {when}
        <key>Hour</key><integer>{t['hour']}</integer>
        <key>Minute</key><integer>{t['minute']}</integer>
    </dict>
    <key>StandardOutPath</key><string>/tmp/myastro-{task}.log</string>
    <key>StandardErrorPath</key><string>/tmp/myastro-{task}.log</string>
</dict>
</plist>
"""


def install(task: str) -> Path:
    """写入 plist 并 launchctl load（幂等：先卸载旧的）。"""
    if task not in TASKS:
        raise LookupError(f"未知任务 {task}（可用: {sorted(TASKS)}）")
    LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)
    p = _plist(task)
    remove(task, quiet=True)
    p.write_text(_render(task))
    subprocess.run(["launchctl", "unload", str(p)],
                   capture_output=True, check=False)             # 确保无旧实例
    subprocess.run(["launchctl", "load", str(p)], check=True,
                   capture_output=True)
    return p


def remove(task: str, quiet: bool = False) -> bool:
    """launchctl unload + 删 plist。返回是否存在过。"""
    if task not in TASKS:
        raise LookupError(f"未知任务 {task}")
    p = _plist(task)
    existed = p.exists()
    if existed:
        subprocess.run(["launchctl", "unload", str(p)],
                       capture_output=True, check=False)
        p.unlink()
    elif not quiet:
        return False
    return existed


def list_installed() -> list[dict]:
    return [{"task": t, "installed": _plist(t).exists(),
             "desc": d["desc"], "when":
             f"{'每周日 ' if d['weekday'] is not None else '每日 '}"
             f"{d['hour']:02d}:{d['minute']:02d}"}
            for t, d in TASKS.items()]
