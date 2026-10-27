"""Compact, LLM-friendly dump of what is on the device screen, used to pick Maestro selectors."""
from __future__ import annotations

import csv
import datetime as dt
import io
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import devices
from .util import UserError, info, require_maestro, run, short

TEXT_ATTRS = ("text", "accessibilityText", "resource-id", "hintText", "value")
FLAG_ATTRS = ("checked", "focused", "selected")


def parse_compact(csv_text: str) -> List[dict]:
    rows = []
    start = csv_text.find("element_num")
    reader = csv.DictReader(io.StringIO(csv_text[start:] if start >= 0 else csv_text))
    for row in reader:
        attrs: Dict[str, str] = {}
        for part in (row.get("attributes") or "").split("; "):
            if "=" in part:
                key, value = part.split("=", 1)
                attrs.setdefault(key.strip(), value.strip())
        rows.append({"num": row.get("element_num"), "depth": int(row.get("depth") or 0), "attrs": attrs})
    return rows


SYSTEM_ID_PREFIXES = ("com.android.systemui:", "android:id/")


def describe(element: dict) -> Optional[str]:
    attrs = element["attrs"]
    resource_id = attrs.get("resource-id", "")
    if resource_id.startswith(SYSTEM_ID_PREFIXES):
        if resource_id.startswith("com.android.systemui:") or not (attrs.get("text") or attrs.get("accessibilityText")):
            return None       # Android status / navigation bar and bare framework containers
    parts = []
    labels = {"text": "text", "accessibilityText": "a11y", "resource-id": "id", "hintText": "hint", "value": "value"}
    seen = set()
    for key in TEXT_ATTRS:
        value = attrs.get(key, "").strip()
        if value and value not in seen:
            seen.add(value)
            parts.append(f'{labels[key]}="{short(value, 90)}"')
    if not parts:
        return None
    flags = [f for f in FLAG_ATTRS if attrs.get(f) == "true"]
    if attrs.get("enabled") == "false":
        flags.append("disabled")
    bounds = attrs.get("bounds", "")
    return f"[{element['num']}] " + "  ".join(parts) + (f"  {bounds}" if bounds else "") + (
        f"  ({', '.join(flags)})" if flags else "")


def inspect(platform: str, out_dir: Path, device_id: Optional[str] = None, flow: Optional[Path] = None,
            env: Optional[Dict[str, str]] = None) -> dict:
    maestro = require_maestro()
    device = devices.resolve_device(platform, device_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    result = {"device": device.label()}
    if flow:
        cmd = [maestro, "test", "--udid", device.id, "--no-reinstall-driver"]
        for key, value in (env or {}).items():
            cmd += ["-e", f"{key}={value}"]
        cmd.append(str(flow))
        info(f"Running {flow.name} to reach the screen...")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        tail = "\n".join(proc.stdout.strip().splitlines()[-4:])
        result["flow"] = {"exit_code": proc.returncode, "output": tail}
        info(tail)
    res = run([maestro, "--udid", device.id, "hierarchy", "--compact", "--no-reinstall-driver"], timeout=240)
    if res.returncode != 0:
        raise UserError(f"maestro hierarchy failed: {short(res.stderr or res.stdout, 400)}")
    raw = out_dir / f"{stamp}-hierarchy.csv"
    raw.write_text(res.stdout, encoding="utf-8")
    lines, seen = [], set()
    for element in parse_compact(res.stdout):
        line = describe(element)
        key = line.split("] ", 1)[-1] if line else None
        if line and key not in seen:
            seen.add(key)
            lines.append(line)
    text_file = out_dir / f"{stamp}-elements.txt"
    text_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shot = out_dir / f"{stamp}-screen.png"
    if devices.screenshot(device, shot):
        result["screenshot"] = str(shot)
    result.update(elements=lines, elements_file=str(text_file), raw=str(raw))
    return result
