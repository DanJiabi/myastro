"""aria2c RPC 客户端：懒启动 daemon，JSON-RPC 交互。

io 不实现传输——并发/续传/限速全在 aria2c；此处只是编排与记账。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import requests

DEFAULT_RPC_PORT = 6800
# 默认密钥保留历史值（老用户的 daemon 就是这么起的），但**可通过环境变量覆盖**——
# 硬编码共享密钥意味着：任何本机进程只要知道这个字符串，就能通过 RPC 控制你的
# aria2（往数据目录塞下载）。配置化是必须的，文档与 doctor 提示都会写明。
DEFAULT_RPC_SECRET = "myastro-legacy"


def rpc_port() -> int:
    import os

    return int(os.environ.get("MYASTRO_ARIA2_PORT", DEFAULT_RPC_PORT))


def rpc_secret() -> str:
    import os

    return os.environ.get("MYASTRO_ARIA2_SECRET", DEFAULT_RPC_SECRET)


def rpc_url() -> str:
    return f"http://127.0.0.1:{rpc_port()}/jsonrpc"


def daemon_command(download_root) -> list[str]:
    """启动守护进程的完整命令（doctor 提示与文档共用同一份，避免写两遍写歪）。"""
    return ["aria2c", "--enable-rpc", f"--rpc-listen-port={rpc_port()}",
            f"--rpc-secret={rpc_secret()}", "-d", str(download_root),
            "--continue=true", "--auto-file-renaming=false",
            "--allow-overwrite=true", "--max-connection-per-server=4",
            "--split=4", "--rpc-listen-all=false"]


def _call(method: str, params: list, *, timeout: float = 30) -> dict:
    payload = {"jsonrpc": "2.0", "id": "myastro",
               "method": f"aria2.{method}",
               "params": [f"token:{rpc_secret()}", *params]}
    r = requests.post(rpc_url(), json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"aria2 {method}: {data['error']}")
    return data["result"]


def ping() -> bool:
    try:
        _call("getGlobalStat", [])
        return True
    except Exception:                                   # noqa: BLE001
        return False


ARIA2_INSTALL_HINT = ("macOS: brew install aria2 | Debian/Ubuntu: sudo apt install aria2"
                       " | Fedora: sudo dnf install aria2 | Arch: sudo pacman -S aria2")


def diagnose(download_root: Path | None = None) -> dict:
    """诊断 aria2 状态：装没装、守护进程起没起、密钥对不对。

    为什么要区分这三件事：`ping()` 只会返回 True/False，于是"daemon 在跑但密钥
    不匹配"会被误报成"离线"，用户按"没启动"去排查，方向就错了。
    """
    import shutil

    binary = shutil.which("aria2c")
    info = {"binary": binary, "daemon": False, "auth_ok": None,
            "secret": rpc_secret(), "port": rpc_port(),
            "install_hint": ARIA2_INSTALL_HINT}
    if ping():
        info["daemon"] = info["auth_ok"] = True
        return info
    # 不带 token 再探一次：能应答说明进程在，只是密钥不匹配
    try:
        requests.post(rpc_url(),
                      json={"jsonrpc": "2.0", "id": "myastro-probe",
                            "method": "aria2.getGlobalStat", "params": []},
                      timeout=3)
        info["daemon"], info["auth_ok"] = True, False
    except requests.RequestException:
        info["daemon"] = False
    return info


def ensure_daemon(download_root: Path) -> None:
    """daemon 不在则拉起（detached）；aria2 控制文件保证重启续传。

    先查二进制再等：aria2 没装时立刻给出跨平台安装提示，而不是先白等 10 秒
    （此前的提示只有 `brew install aria2`，Linux 用户照着做不了）。
    """
    import shutil

    if ping():
        return
    if shutil.which("aria2c") is None:
        raise RuntimeError(
            f"未安装 aria2：批量下载（legacy / ztf / manifest 清单）需要它。"
            f"安装：{ARIA2_INSTALL_HINT}；装好后 myastro 会在首次使用时自动拉起守护进程。")
    download_root = Path(download_root)
    download_root.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(daemon_command(download_root),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(20):
        if ping():
            return
        time.sleep(0.5)
    state = diagnose()
    if state["daemon"] and state["auth_ok"] is False:
        raise RuntimeError(
            f"aria2 守护进程在运行，但密钥不匹配（本机期望 {state['secret']!r}）。"
            f"要么用 --rpc-secret={state['secret']} 重启 daemon，"
            f"要么设 MYASTRO_ARIA2_SECRET 与你的 daemon 一致。")
    raise RuntimeError(
        f"aria2c 启动失败（二进制：{state['binary']}）。手动启动试试：\n  "
        + " ".join(daemon_command(download_root)))


def add_uri(url: str, dest_dir: Path, out_name: str) -> str:
    options = {"dir": str(dest_dir), "out": out_name,
               "continue": "true", "allow-overwrite": "true"}
    gid = _call("addUri", [[url], options])
    return gid


def status(gid: str) -> dict:
    """tellStatus 精简：返回 status/completedLength/totalLength/downloadSpeed/errorCode."""
    keys = ["status", "completedLength", "totalLength",
            "downloadSpeed", "errorCode", "errorMessage"]
    s = _call("tellStatus", [gid, keys])
    return {k: s.get(k) for k in keys}


def remove(gid: str) -> None:
    """请求取消下载；失败静默（已完结/不存在的 gid 是常态）。

    只吞 `_call` 真实会抛的三类：HTTP 层请求异常、RPC 返回 error（RuntimeError）、
    JSON 解析失败（ValueError）。收窄后既保留"取消是尽力而为"的语义，
    又不会把程序错误一起吞掉。
    """
    try:
        _call("remove", [gid])
    except (requests.RequestException, RuntimeError, ValueError):
        pass
