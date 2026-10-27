"""Environment check: everything needed to run Maestro smoke tests and write the Excel report."""
from __future__ import annotations

import platform as host
import re
import shutil
import sys
from typing import List, Optional

from . import devices, metro
from .util import maestro_bin, run

MAESTRO_INSTALL = 'curl -fsSL "https://get.maestro.mobile.dev" | bash && export PATH="$PATH:$HOME/.maestro/bin"'


def _item(name: str, ok: Optional[bool], detail: str, fix: str = "", required: bool = True) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "fix": fix, "required": required}


def check(platform: str = "all") -> List[dict]:
    items = []
    py_ok = sys.version_info >= (3, 9)
    items.append(_item("python", py_ok, sys.version.split()[0], "Install Python 3.9+"))
    try:
        import openpyxl  # noqa: F401

        items.append(_item("openpyxl", True, openpyxl.__version__))
    except ImportError:
        items.append(_item("openpyxl", False, "missing", "scripts/rnsmoke bootstraps a venv automatically; "
                                                        "or: python3 -m pip install openpyxl"))

    java = run(["java", "-version"], timeout=20)
    match = re.search(r'version "(\d+)(?:\.(\d+))?', java.stderr + java.stdout)
    major = int(match.group(1)) if match else 0
    if major == 1 and match and match.group(2):
        major = int(match.group(2))
    items.append(_item("java", major >= 17, (java.stderr or java.stdout).splitlines()[0] if java.returncode == 0 else "missing",
                       "Maestro needs Java 17+: brew install openjdk@17 (and put it on PATH / set JAVA_HOME)"))

    maestro = maestro_bin()
    version = run([maestro, "--version"], timeout=60).stdout.strip().splitlines()[-1:] if maestro else []
    items.append(_item("maestro", bool(maestro), f"{version[0] if version else ''} ({maestro})" if maestro else "missing",
                       MAESTRO_INSTALL))

    ios_ready = android_ready = False
    if platform in ("all", "ios"):
        if host.system() != "Darwin":
            items.append(_item("xcode", None, "iOS simulators need macOS", required=False))
        else:
            xcode = run(["xcodebuild", "-version"], timeout=30)
            items.append(_item("xcode", xcode.returncode == 0,
                               " ".join(xcode.stdout.split()[:2]) if xcode.returncode == 0 else "missing",
                               "Install Xcode from the App Store, then: sudo xcode-select -s /Applications/Xcode.app",
                               required=platform == "ios"))
            booted = devices.ios_booted()
            ios_ready = bool(booted)
            items.append(_item("ios simulator", bool(booted), ", ".join(d.label() for d in booted) or "none booted",
                               'open -a Simulator   (or: xcrun simctl boot "iPhone 15")', required=platform == "ios"))
    if platform in ("all", "android"):
        adb = shutil.which("adb")
        items.append(_item("adb", bool(adb), adb or "missing",
                           "Install Android Studio / platform-tools and add $ANDROID_HOME/platform-tools to PATH",
                           required=platform == "android"))
        connected = devices.android_connected() if adb else []
        android_ready = bool(connected)
        listing = run(["emulator", "-list-avds"], timeout=20).stdout if shutil.which("emulator") else ""
        avds = [line.strip() for line in listing.splitlines() if line.strip() and not re.search(r"[\s|]", line.strip())]
        items.append(_item("android device", bool(connected),
                           ", ".join(d.label() for d in connected) or f"none connected (AVDs: {', '.join(avds) or 'none'})",
                           "emulator -avd <name> &", required=platform == "android"))
    if platform == "all":
        items.append(_item("any device", ios_ready or android_ready,
                           "ready" if (ios_ready or android_ready) else "boot an iOS simulator or an Android emulator",
                           'open -a Simulator  |  emulator -avd <name>'))

    node = run(["node", "--version"], timeout=20)
    items.append(_item("node", node.returncode == 0, node.stdout.strip() or "missing",
                       "Install Node.js (needed for Metro / building the app)", required=False))
    items.append(_item("metro :8081", metro.is_running(8081) or None,
                       "running" if metro.is_running(8081) else "not running (only needed for debug builds)",
                       "rnsmoke metro start", required=False))
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    items.append(_item("libreoffice", bool(soffice) or None, soffice or "not installed (only for --xls output)",
                       "brew install --cask libreoffice", required=False))
    return items


def render(items: List[dict]) -> str:
    lines = []
    for item in items:
        mark = "OK " if item["ok"] else ("-- " if item["ok"] is None or not item["required"] else "XX ")
        lines.append(f"[{mark}] {item['name']:<15} {item['detail']}")
        if not item["ok"] and item["fix"]:
            lines.append(f"       fix: {item['fix']}")
    return "\n".join(lines)


def blocking(items: List[dict]) -> List[dict]:
    return [i for i in items if i["required"] and not i["ok"]]
