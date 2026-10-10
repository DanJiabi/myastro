"""aria2c RPC 客户端：懒启动 daemon，JSON-RPC 交互。

io 不实现传输——并发/续传/限速全在 aria2c；此处只是编排与记账。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import requests

RPC_PORT = 6800
RPC_SECRET = "myastro-legacy"
RPC_URL = f"http://127.0.0.1:{RPC_PORT}/jsonrpc"


def _call(method: str, params: list, *, timeout: float = 30) -> dict:
    payload = {"jsonrpc": "2.0", "id": "myastro",
               "method": f"aria2.{method}",
               "params": [f"token:{RPC_SECRET}", *params]}
    r = requests.post(RPC_URL, json=payload, timeout=timeout)
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


def ensure_daemon(download_root: Path) -> None:
    """daemon 不在则拉起（detached）；aria2 控制文件保证重启续传。"""
    if ping():
        return
    download_root = Path(download_root)
    download_root.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        ["aria2c", "--enable-rpc", f"--rpc-listen-port={RPC_PORT}",
         f"--rpc-secret={RPC_SECRET}", "-d", str(download_root),
         "--continue=true", "--auto-file-renaming=false",
         "--allow-overwrite=true", "--max-connection-per-server=4",
         "--split=4", "--rpc-listen-all=false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    for _ in range(20):
        if ping():
            return
        time.sleep(0.5)
    raise RuntimeError("aria2c daemon 启动失败（aria2c 是否在 PATH？brew install aria2）")


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
