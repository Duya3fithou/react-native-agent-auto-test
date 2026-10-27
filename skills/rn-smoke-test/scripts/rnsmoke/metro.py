"""Start / stop / check the Metro bundler that React Native debug builds load JavaScript from."""
from __future__ import annotations

import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from .util import UserError, info, read_json


def is_running(port: int = 8081) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as resp:
            return "packager-status:running" in resp.read().decode(errors="replace")
    except OSError:
        return False


def _command(project: Path, port: int) -> List[str]:
    pkg = read_json(project / "package.json", {}) or {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    bin_dir = project / "node_modules" / ".bin"
    if not bin_dir.exists():
        raise UserError(f"{project}/node_modules is missing - install JS dependencies first (yarn / npm install).")
    if "expo" in deps and (bin_dir / "expo").exists():
        return [str(bin_dir / "expo"), "start", "--port", str(port)]
    if (bin_dir / "react-native").exists():
        return [str(bin_dir / "react-native"), "start", "--port", str(port)]
    raise UserError("Could not find the react-native or expo CLI in node_modules/.bin")


def _prewarm(port: int, platform: str, entry: str = "index") -> None:
    """Build the JS bundle once so the first app launch inside a flow does not time out."""
    url = f"http://127.0.0.1:{port}/{entry}.bundle?platform={platform}&dev=true&minify=false"
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=600) as resp:
            size = len(resp.read())
        info(f"Pre-built the {platform} bundle ({size // 1024} KB) in {time.time() - started:.0f}s")
    except OSError as exc:
        info(f"Bundle pre-build skipped ({exc}); the first launch may be slow.")


def start(project: Path, pid_file: Path, log_file: Path, port: int = 8081,
          platforms: Optional[List[str]] = None, timeout: int = 180) -> dict:
    if is_running(port):
        info(f"Metro is already running on port {port}.")
        for platform in platforms or []:
            _prewarm(port, platform)
        return {"running": True, "started": False, "port": port}
    cmd = _command(project, port)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CI="1", BROWSER="none")
    with log_file.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=str(project), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_running(port):
            info(f"Metro started (pid {proc.pid}, port {port}); log: {log_file}")
            for platform in platforms or []:
                _prewarm(port, platform)
            return {"running": True, "started": True, "pid": proc.pid, "port": port, "log": str(log_file)}
        if proc.poll() is not None:
            break
        time.sleep(2)
    tail = log_file.read_text(encoding="utf-8", errors="replace")[-1500:] if log_file.exists() else ""
    raise UserError(f"Metro did not come up on port {port}. Last log lines:\n{tail}")


def stop(pid_file: Path, port: int = 8081) -> bool:
    if not pid_file.exists():
        if is_running(port):
            info(f"Metro on port {port} was not started by rnsmoke; leaving it running.")
        return False
    pid = int(pid_file.read_text(encoding="utf-8").strip() or 0)
    pid_file.unlink()
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    for _ in range(20):
        if not is_running(port):
            break
        time.sleep(0.5)
    info(f"Metro (pid {pid}) stopped.")
    return True
