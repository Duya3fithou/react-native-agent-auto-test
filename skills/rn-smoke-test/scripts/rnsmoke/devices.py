"""Simulator / emulator helpers: discovery, installed-app info, screenshots and screen recording."""
from __future__ import annotations

import json
import plistlib
import re
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from .util import UserError, run, warn


@dataclass
class Device:
    platform: str
    id: str
    name: str
    os: str = ""

    def label(self) -> str:
        return f"{self.name} ({self.os}) [{self.id}]"

    def to_dict(self) -> dict:
        return asdict(self)


def ios_booted() -> List[Device]:
    res = run(["xcrun", "simctl", "list", "devices", "booted", "-j"], timeout=30)
    if res.returncode != 0:
        return []
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return []
    found = []
    for runtime, items in (data.get("devices") or {}).items():
        # com.apple.CoreSimulator.SimRuntime.iOS-27-0 -> "iOS 27.0"
        os_name = re.sub(r"^(\w+)-(\d+)-(\d+)$", r"\1 \2.\3", runtime.rsplit(".", 1)[-1])
        for item in items:
            if item.get("state") == "Booted":
                found.append(Device("ios", item["udid"], item.get("name", "Simulator"), os_name))
    return found


def android_connected() -> List[Device]:
    res = run(["adb", "devices"], timeout=30)
    if res.returncode != 0:
        return []
    found = []
    for line in res.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            model = run(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=15).stdout.strip()
            release = run(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], timeout=15).stdout.strip()
            found.append(Device("android", serial, model or serial, f"Android {release}".strip()))
    return found


def list_devices(platform: str) -> List[Device]:
    return ios_booted() if platform == "ios" else android_connected()


def resolve_device(platform: str, wanted: Optional[str] = None) -> Device:
    available = list_devices(platform)
    if wanted:
        for device in available:
            if wanted in (device.id, device.name) or device.name.lower() == wanted.lower():
                return device
        listing = ", ".join(d.label() for d in available) or "none"
        raise UserError(f"{platform} device '{wanted}' is not booted/connected. Available: {listing}")
    if not available:
        hint = ('Boot a simulator: open -a Simulator  (or: xcrun simctl boot "iPhone 15")' if platform == "ios"
                else "Start an emulator: emulator -avd <name>   (list them with: emulator -list-avds)")
        raise UserError(f"No {platform} device available. {hint}")
    if len(available) > 1:
        warn(f"Several {platform} devices found; using {available[0].label()} (choose with --device)")
    return available[0]


# --------------------------------------------------------------------------- installed app

def app_info(device: Device, app_id: str) -> dict:
    return _ios_app_info(device, app_id) if device.platform == "ios" else _android_app_info(device, app_id)


def _ios_app_info(device: Device, bundle_id: str) -> dict:
    res = run(["xcrun", "simctl", "get_app_container", device.id, bundle_id, "app"], timeout=30)
    if res.returncode != 0:
        return {"installed": False, "id": bundle_id}
    container = Path(res.stdout.strip())
    info = {"installed": True, "id": bundle_id, "path": str(container)}
    executable = ""
    try:
        with (container / "Info.plist").open("rb") as fh:
            plist = plistlib.load(fh)
        info.update(version=plist.get("CFBundleShortVersionString"), build=plist.get("CFBundleVersion"),
                    name=plist.get("CFBundleDisplayName") or plist.get("CFBundleName"))
        executable = plist.get("CFBundleExecutable") or ""
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    bundled_js = any((container / name).exists() for name in ("main.jsbundle", "index.ios.bundle"))
    debug_dylib = bool(executable) and (container / f"{executable}.debug.dylib").exists()
    info["debug"] = debug_dylib or not bundled_js
    info["bundled_js"] = bundled_js
    return info


def _android_app_info(device: Device, package: str) -> dict:
    res = run(["adb", "-s", device.id, "shell", "dumpsys", "package", package], timeout=30)
    if res.returncode != 0 or f"Package [{package}]" not in res.stdout:
        return {"installed": False, "id": package}
    version = re.search(r"versionName=(\S+)", res.stdout)
    code = re.search(r"versionCode=(\d+)", res.stdout)
    flags = re.search(r"pkgFlags=\[([^\]]*)\]", res.stdout)
    return {
        "installed": True,
        "id": package,
        "version": version.group(1) if version else None,
        "build": code.group(1) if code else None,
        "debug": bool(flags and "DEBUGGABLE" in flags.group(1)),
    }


def adb_reverse(device: Device, port: int) -> bool:
    return run(["adb", "-s", device.id, "reverse", f"tcp:{port}", f"tcp:{port}"], timeout=20).returncode == 0


# --------------------------------------------------------------------------- capture

def screenshot(device: Device, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if device.platform == "ios":
        return run(["xcrun", "simctl", "io", device.id, "screenshot", str(path)], timeout=30).returncode == 0
    try:
        with path.open("wb") as fh:
            return subprocess.run(["adb", "-s", device.id, "exec-out", "screencap", "-p"], stdout=fh,
                                  stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Recorder:
    """Screen recording around a single flow (iOS: simctl recordVideo, Android: screenrecord <= 3 min)."""

    def __init__(self, device: Device, path: Path):
        self.device, self.path = device, path
        self.proc: Optional[subprocess.Popen] = None
        self.remote = f"/sdcard/rnsmoke-{int(time.time())}.mp4"

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.device.platform == "ios":
            cmd = ["xcrun", "simctl", "io", self.device.id, "recordVideo", "--codec=h264", "--force", str(self.path)]
        else:
            cmd = ["adb", "-s", self.device.id, "shell", "screenrecord", "--bit-rate", "4000000", self.remote]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
        except OSError as exc:
            warn(f"screen recording not started: {exc}")
            self.proc = None

    def stop(self) -> Optional[Path]:
        if not self.proc:
            return None
        try:
            if self.device.platform == "ios":
                self.proc.send_signal(signal.SIGINT)
                self.proc.wait(timeout=30)
            else:
                run(["adb", "-s", self.device.id, "shell", "pkill", "-INT", "screenrecord"], timeout=15)
                try:
                    self.proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                time.sleep(1.5)
                run(["adb", "-s", self.device.id, "pull", self.remote, str(self.path)], timeout=180)
                run(["adb", "-s", self.device.id, "shell", "rm", "-f", self.remote], timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return self.path if self.path.exists() and self.path.stat().st_size > 0 else None
