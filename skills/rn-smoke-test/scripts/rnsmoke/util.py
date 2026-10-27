"""Small shared helpers: paths, text folding, JSON IO, subprocess and console output."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Optional, Sequence

PACKAGE_DIR = Path(__file__).resolve().parent
SKILL_DIR = PACKAGE_DIR.parents[1]
TEMPLATES_DIR = SKILL_DIR / "templates"


class UserError(Exception):
    """An actionable problem (missing tool, bad input...). Printed without a traceback."""


# --------------------------------------------------------------------------- console

def info(message: str = "") -> None:
    print(message, file=sys.stderr)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


# --------------------------------------------------------------------------- text

def fold(value: Any) -> str:
    """Lower-case, accent-free, whitespace-collapsed text used for fuzzy matching."""
    if value is None:
        return ""
    text = str(value).replace("đ", "d").replace("Đ", "D").replace(" ", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def clean(value: Any) -> Any:
    """Strip strings and turn blank strings into None; other types pass through."""
    if isinstance(value, str):
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        return value or None
    return value


def as_text(value: Any) -> str:
    value = clean(value)
    return "" if value is None else str(value)


def slugify(text: Any, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return slug[:max_len].rstrip("-") or "case"


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def short(text: Any, limit: int = 160) -> str:
    flat = re.sub(r"\s+", " ", as_text(text))
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# --------------------------------------------------------------------------- json

def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    """Atomic JSON write so an interrupted run never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o644)  # mkstemp creates 0600; these files are meant to be shared / committed
    os.replace(tmp, path)


# --------------------------------------------------------------------------- processes

def run(args: Sequence[str], timeout: float = 60, cwd: Optional[Path] = None,
        env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run a command capturing text output. Never raises for missing binaries,
    non-zero exits or timeouts (exit codes 127 / 124 are used instead)."""
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout,
                              cwd=str(cwd) if cwd else None, env=env)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(list(args), 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(list(args), 124, out, f"timed out after {timeout:.0f}s")


def maestro_bin() -> Optional[str]:
    explicit = os.environ.get("MAESTRO_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("maestro")
    if found:
        return found
    fallback = Path.home() / ".maestro" / "bin" / "maestro"
    return str(fallback) if fallback.exists() else None


def require_maestro() -> str:
    path = maestro_bin()
    if not path:
        raise UserError('Maestro CLI not found. Install it with: curl -fsSL "https://get.maestro.mobile.dev" | bash '
                        '(then: export PATH="$PATH:$HOME/.maestro/bin")')
    return path


def git_user_name() -> str:
    res = run(["git", "config", "user.name"], timeout=5)
    return res.stdout.strip() if res.returncode == 0 else os.environ.get("USER", "")
