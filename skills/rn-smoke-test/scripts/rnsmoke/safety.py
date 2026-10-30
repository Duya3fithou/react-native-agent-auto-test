"""Data-safety guard: a smoke session may change the data of ONE test account and nothing else.

Every flow (and every subflow it runs) is scanned before `rnsmoke run`, `mark --flow` and
`inspect --flow` execute it. A flow with a violation is not run - the case is reported as blocked with
the reason. The guard has no off switch.

Rules
  identity  text typed into the app may identify only the session account (${TEST_EMAIL},
            ${TEST_USERNAME}, ${TEST_PHONE}, ${TEST_PASSWORD}). Literal or generated e-mail addresses,
            inputRandomEmail / inputRandomPersonName and any other account variable (TEST_EMAIL_2,
            ADMIN_PASSWORD, PASSWORD...) are refused.
  account   taps that create, register or delete accounts/profiles, or change/reset a password.
  script    evalScript / runScript calls that write over HTTP (http.post/put/patch/delete).
  records   taps that create or remove records (book, join, buy, pay, submit, send, post, add, delete...).
  edit      taps that save changes (save, update, change, confirm) - allowed only for cases declared
            `--data account`: idempotent edits of the session account's own fields.
  unverifiable  coordinate-only taps, unreadable subflows/scripts.

`records`, `edit` and `unverifiable` findings that are NOT data changes (a bottom tab called "Book", a
date-picker overlay tapped by coordinates, "Add to calendar" writing only the device calendar) can be
cleared by an annotation in the same flow file; `status` lists every one for human review:
    # rnsmoke-safe-tap: "Book" -- bottom tab, navigation only
`identity`, `account` and `script` findings can never be cleared.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .util import UserError, read_json, warn, write_json

ALLOWED_IDENTITY = ("TEST_EMAIL", "TEST_USERNAME", "TEST_PHONE", "TEST_PASSWORD")
IDENTITY_TOKENS = {"EMAIL", "MAIL", "USER", "USERNAME", "LOGIN", "PHONE", "PASS", "PASSWORD", "PWD", "PIN",
                   "ACCOUNT", "CREDENTIAL", "CREDENTIALS"}
DATA_LEVELS = ("none", "account")
HARD_RULES = ("identity", "account", "script")

ACCOUNT_RE = re.compile(
    r"\b(create\s+(an?\s+|new\s+)?(account|profile|user)|sign\s*-?\s*up|register|registration|join\s+now|"
    r"(delete|remove|close|deactivate|cancel)\s+(my\s+|this\s+|your\s+|the\s+)?account|deactivate|"
    r"add\s+(a\s+|new\s+)?(profile|user|member|child|athlete)|"
    r"(change|reset|update|set)\s+(my\s+|your\s+|the\s+|new\s+)?password|new\s+password)\b", re.I)
RECORDS_RE = re.compile(
    r"\b(book|booking|reserve|join|waitlist|enrol+|purchase|buy|pay|payment|checkout|check\s*out|subscribe|"
    r"submit|send|post|publish|upload|claim|redeem|order|invite|add|create|delete|remove|request|"
    r"cancel\s+\w+|sign\s+(the\s+)?(waiver|agreement|contract))\b", re.I)
EDIT_RE = re.compile(r"\b(save|update|change|confirm)\b", re.I)
HTTP_WRITE_RE = re.compile(r"\bhttp\s*\.\s*(post|put|patch|delete|request)\b", re.I)
EMAIL_RE = re.compile(r"@[\w${}.-]*\.[a-z]{2,}|\}\s*@|@\s*\$\{", re.I)
VAR_RE = re.compile(r"\$\{\s*([A-Za-z_]\w*)\s*\}")
ANNOTATION_RE = re.compile(r"#\s*rnsmoke-safe-tap:\s*\"?(.+?)\"?\s+--\s+(\S.*)$")
TAP_KEYS = ("tapOn", "longPressOn", "doubleTapOn")
RANDOM_IDENTITY = ("inputRandomEmail", "inputRandomPersonName")


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    text: str
    allowed_by: Optional[str] = None      # annotation reason when a soft finding was cleared

    def describe(self) -> str:
        return f"{self.rule}: {Path(self.file).name}:{self.line} '{self.text}'"


@dataclass
class _Line:
    no: int
    indent: int
    key: Optional[str]
    value: str
    body: str


def is_identity_var(name: str) -> bool:
    tokens = [t for t in re.split(r"[_\W]+", name.upper()) if t]
    return any(t in IDENTITY_TOKENS or t.startswith(("EMAIL", "PASSWORD")) for t in tokens)


# --------------------------------------------------------------------------- tiny YAML reader

def _strip_comment(raw: str) -> str:
    quote = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _parse(text: str) -> List[_Line]:
    lines = []
    for no, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        while body == "-" or body.startswith("- "):     # "- key: value" -> key at the item's indent
            rest = body[1:]
            indent += 1 + len(rest) - len(rest.lstrip(" "))
            body = rest.lstrip(" ")
        if not body:
            continue
        match = re.match(r"^([A-Za-z_][\w-]*)\s*:(?:\s+(.*))?$", body)
        key, value = (match.group(1), (match.group(2) or "").strip()) if match else (None, body)
        lines.append(_Line(no, indent, key, value, body))
    return lines


def _children(lines: List[_Line], index: int) -> Dict[str, Tuple[_Line, int]]:
    """Direct children (key -> (line, index)) of the block that starts at lines[index]."""
    parent, kids, child_indent = lines[index].indent, {}, None
    for j in range(index + 1, len(lines)):
        line = lines[j]
        if line.indent <= parent:
            break
        child_indent = line.indent if child_indent is None else child_indent
        if line.indent == child_indent and line.key and line.key not in kids:
            kids[line.key] = (line, j)
    return kids


# --------------------------------------------------------------------------- scanning

def _annotations(text: str) -> Dict[str, str]:
    found = {}
    for raw in text.splitlines():
        match = ANNOTATION_RE.search(raw)
        if match:
            found[match.group(1).strip().lower()] = match.group(2).strip()
    return found


def _plain(selector: str) -> str:
    """Selector regex -> plain words for keyword matching."""
    text = re.sub(r"\(\?[a-z]+\)", " ", selector)
    text = re.sub(r"\\[a-zA-Z]|\.\*|\.\+|[\\^$()\[\]{}?+*|.]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _without_session_vars(value: str) -> str:
    return VAR_RE.sub(lambda m: "" if m.group(1) in ALLOWED_IDENTITY else m.group(0), value)


def _identity_text(raw: str, resolved: str, file: str, no: int, what: str) -> List[Finding]:
    found = [Finding("identity", file, no, f"${{{name}}} is not the session account")
             for name in VAR_RE.findall(raw) if is_identity_var(name) and name not in ALLOWED_IDENTITY]
    if EMAIL_RE.search(_without_session_vars(resolved)):
        found.append(Finding("identity", file, no, f"{what} an e-mail address other than ${{TEST_EMAIL}}: {raw}"))
    return found


def _classify_tap(target: str, level: str) -> Optional[str]:
    if target.startswith("point "):
        return "unverifiable"
    words = _plain(target)
    if ACCOUNT_RE.search(words):
        return "account"
    if RECORDS_RE.search(words):
        return "records"
    if EDIT_RE.search(words) and level != "account":
        return "edit"
    return None


def _env(lines: List[_Line], index: int) -> Dict[str, Tuple[str, int]]:
    return {key: (_scalar(line.value), line.no) for key, (line, _) in _children(lines, index).items()}


def _scan(path: Path, level: str, env: Dict[str, str], seen: Set[Tuple[str, str]], out: List[Finding]) -> None:
    key = (str(path.resolve()), json.dumps(env, sort_keys=True))
    if key in seen:
        return
    seen.add(key)
    file = str(path)
    if not path.is_file():
        out.append(Finding("unverifiable", file, 0, "subflow file not found - cannot be checked"))
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    allow, lines, local = _annotations(text), _parse(text), []

    def resolve(value: str) -> str:
        return VAR_RE.sub(lambda m: env.get(m.group(1), m.group(0)), value)

    def tap(target: str, no: int) -> None:
        target = resolve(_scalar(target))
        rule = _classify_tap(target, level)
        if rule:
            local.append(Finding(rule, file, no, target))

    for i, line in enumerate(lines):
        name = line.key or line.body
        if name in RANDOM_IDENTITY:
            local.append(Finding("identity", file, line.no, f"{name} invents a new identity"))
        elif line.key in TAP_KEYS:
            kids = _children(lines, i) if not line.value else {}
            if line.value:
                tap(line.value, line.no)
            elif "text" in kids or "id" in kids:
                target = (kids.get("text") or kids.get("id"))[0]
                tap(target.value, target.no)
            elif "point" in kids:
                tap(f"point {_scalar(kids['point'][0].value)}", kids["point"][0].no)
        elif line.key == "inputText":
            source = line if line.value else _children(lines, i).get("text", (None, 0))[0]
            if source is not None:
                raw = _scalar(source.value)
                local += _identity_text(raw, resolve(raw), file, source.no, "types")
        elif line.key == "env" and not line.value:
            for var, (value, no) in _env(lines, i).items():
                if is_identity_var(var) and var not in ALLOWED_IDENTITY:
                    local.append(Finding("identity", file, no, f"passes account variable {var}"))
                local += _identity_text(value, resolve(value), file, no, "passes")
        elif line.key == "evalScript" and HTTP_WRITE_RE.search(line.value):
            local.append(Finding("script", file, line.no, "evalScript writes over HTTP"))
        elif line.key == "runScript":
            script = line.value or _children(lines, i).get("file", (_Line(0, 0, None, "", ""), 0))[0].value
            script_path = path.parent / _scalar(script) if script else None
            if not script_path or not script_path.is_file():
                local.append(Finding("unverifiable", file, line.no, f"script not found: {script}"))
            elif HTTP_WRITE_RE.search(script_path.read_text(encoding="utf-8", errors="replace")):
                local.append(Finding("script", file, line.no, f"{script_path.name} writes over HTTP"))
        elif line.key == "runFlow":
            if line.value and not line.value.startswith("{"):
                _scan(path.parent / _scalar(line.value), level, {}, seen, out)
            else:
                kids = _children(lines, i)
                if "file" in kids:
                    sub_env = ({var: resolve(value) for var, (value, _) in _env(lines, kids["env"][1]).items()}
                               if "env" in kids else {})
                    _scan(path.parent / _scalar(kids["file"][0].value), level, sub_env, seen, out)

    for finding in local:
        if finding.rule not in HARD_RULES and finding.text.lower() in allow:
            finding.allowed_by = allow[finding.text.lower()]
        out.append(finding)


def check_flow(path: Path, level: str = "none") -> List[Finding]:
    """All findings for a flow and its subflows (cleared soft findings carry `allowed_by`)."""
    if level not in DATA_LEVELS:
        raise UserError(f"Unknown data level '{level}' (none | account)")
    findings: List[Finding] = []
    _scan(Path(path), level, {}, set(), findings)
    return findings


def violations(findings: List[Finding]) -> List[Finding]:
    return [f for f in findings if not f.allowed_by]


def summary(found: List[Finding], limit: int = 3) -> str:
    text = "; ".join(f.describe() for f in found[:limit])
    more = f" (+{len(found) - limit} more)" if len(found) > limit else ""
    return f"Data-safety guard: {text}{more}"


def require_safe(path: Path, level: str = "none") -> List[Finding]:
    """Raise listing every violation; otherwise return the annotated exceptions (for review)."""
    found = check_flow(path, level)
    bad = violations(found)
    if bad:
        listing = "\n".join(f"  - {f.describe()}" for f in bad)
        raise UserError(f"{Path(path).name} breaks the data-safety rules (one test account, no new accounts or "
                        f"records):\n{listing}\nRewrite the flow, or mark the case --manual with the reason.")
    return [f for f in found if f.allowed_by]


# --------------------------------------------------------------------------- session account

def filter_env(env: Dict[str, str]) -> Dict[str, str]:
    """Drop every account variable except the single session account before anything reaches Maestro."""
    dropped = sorted(k for k in env if is_identity_var(k) and k not in ALLOWED_IDENTITY)
    if dropped:
        warn(f"ignoring extra account variables (one test account per session): {', '.join(dropped)}")
    return {k: v for k, v in env.items() if k not in dropped}


def _mask(identity: str) -> str:
    if "@" in identity:
        user, domain = identity.split("@", 1)
        return f"{user[:2]}***@{domain}"
    return identity[:2] + "***"


def lock_session(run_dir: Path, env: Dict[str, str]) -> Optional[str]:
    """Record the run's test account; refuse a different account later in the same run."""
    identity = next((env[k] for k in ("TEST_EMAIL", "TEST_USERNAME", "TEST_PHONE") if env.get(k)), "")
    path = run_dir / "session.json"
    session = read_json(path, None) or {}
    if not identity:
        return session.get("account_masked")
    fingerprint = hashlib.sha256(identity.strip().lower().encode()).hexdigest()[:16]
    if session.get("account") and session["account"] != fingerprint:
        raise UserError(f"This run already used the test account {session.get('account_masked')}. One account per "
                        "smoke session: restore that account in .maestro/smoke/.env, or start a new run.")
    if not session.get("account"):
        write_json(path, {"account": fingerprint, "account_masked": _mask(identity)})
    return _mask(identity)
