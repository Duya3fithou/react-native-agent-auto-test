"""Upload evidence files so the links in the report work for other people.

Prefer `gdrive` (the company's Google Drive: private by default, least-privilege scope, deletable).
The free public hosts (catbox, litterbox, imgbb) PUBLISH the screenshots/videos: anyone holding a link
can open them, and anonymous uploads usually cannot be deleted. Only upload when the user asked for
shareable links, and tell them which host, visibility and retention were used.

Links are cached per run in runs/<stamp>/uploads.json (keyed by file path + SHA-256), so exporting
again never uploads the same file twice. A failed upload never breaks the export: that cell keeps
its local link.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .util import UserError, info, now_iso, read_json, run, short, warn, write_json

CACHE_FILE = "uploads.json"
ROOT_DRIVE_FOLDER = "RN smoke evidence"
USER_AGENT = "rnsmoke/1.0"
LITTERBOX_TIMES = ("1h", "12h", "24h", "72h")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class UploadError(Exception):
    """The host refused the file or answered with something that is not a link."""


@dataclass
class Host:
    name: str
    summary: str
    upload: Callable[[Path, dict], str]
    max_mb: int
    images_only: bool = False
    prepare: Optional[Callable[[Path, dict], dict]] = None   # run once before the first real upload


# --------------------------------------------------------------------------- HTTP

def _multipart(fields: Dict[str, str], file_field: str, path: Path):
    boundary = "----rnsmoke" + uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
             for key, value in fields.items()]
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n".encode())
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post(url: str, body: bytes, content_type: str, timeout: int = 180,
          headers: Optional[Dict[str, str]] = None) -> bytes:
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": content_type, "User-Agent": USER_AGENT,
                                              **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _expect_link(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if not re.match(r"^https://\S+$", text):
        raise UploadError(short(text or "empty response", 200))
    return text


# --------------------------------------------------------------------------- hosts

def _catbox(path: Path, opts: dict) -> str:
    fields = {"reqtype": "fileupload"}
    userhash = opts.get("userhash") or os.environ.get("CATBOX_USERHASH")
    if userhash:
        fields["userhash"] = userhash          # files then show up (and can be deleted) in that account
    body, ctype = _multipart(fields, "fileToUpload", path)
    return _expect_link(_post("https://catbox.moe/user/api.php", body, ctype))


def _litterbox(path: Path, opts: dict) -> str:
    expire = opts.get("expire") or "72h"
    if expire not in LITTERBOX_TIMES:
        raise UserError(f"litterbox keeps files for {', '.join(LITTERBOX_TIMES)} only (got --expire {expire})")
    body, ctype = _multipart({"reqtype": "fileupload", "time": expire}, "fileToUpload", path)
    return _expect_link(_post("https://litterbox.catbox.moe/resources/internals/api.php", body, ctype))


def _imgbb(path: Path, opts: dict) -> str:
    key = opts.get("api_key") or os.environ.get("IMGBB_API_KEY")
    if not key:
        raise UserError("imgbb needs a free API key: create one at https://api.imgbb.com and "
                        "export IMGBB_API_KEY=<key>")
    fields = {}
    if opts.get("expire"):
        fields["expiration"] = str(max(60, min(15552000, parse_duration(opts["expire"]))))
    body, ctype = _multipart(fields, "image", path)
    raw = _post("https://api.imgbb.com/1/upload?key=" + urllib.parse.quote(key), body, ctype)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise UploadError(short(raw.decode("utf-8", "replace"), 200)) from exc
    url = ((data.get("data") or {}).get("url") or "") if data.get("success") else ""
    if not url.startswith("https://"):
        raise UploadError(short(json.dumps(data.get("error") or data), 200))
    return url


def _droplr(path: Path, opts: dict) -> str:
    """Droplr (d.pr), same call as the official droplr-js client: POST /files?filename=<name> with the
    raw bytes. Credentials come from the shell environment only (never from files or flows)."""
    token = os.environ.get("DROPLR_TOKEN")
    user = os.environ.get("DROPLR_USERNAME") or os.environ.get("DROPLR_EMAIL")
    password = os.environ.get("DROPLR_PASSWORD")
    if token:
        auth = f"Bearer {token}"
    elif user and password:
        auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    else:
        raise UserError("Droplr needs credentials in the environment: DROPLR_USERNAME=<email> and "
                        "DROPLR_PASSWORD=<password> (or DROPLR_TOKEN=<jwt>)")
    params = {"filename": path.name}
    if os.environ.get("DROPLR_BOARD"):
        params["board"] = os.environ["DROPLR_BOARD"]
    base = os.environ.get("DROPLR_API_URL", "https://api.droplr.com").rstrip("/")
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        raw = _post(f"{base}/files?{urllib.parse.urlencode(params)}", path.read_bytes(), ctype,
                    headers={"Authorization": auth, "Accept": "application/json"})
    except urllib.error.HTTPError as exc:
        try:
            detail = short(exc.read().decode("utf-8", "replace"), 200)
        except Exception:  # noqa: BLE001 - the body is only used for the message
            detail = ""
        if exc.code in (401, 403):
            raise UserError(f"Droplr refused the credentials (HTTP {exc.code}) {detail}. Accounts that sign in "
                            "with Google/SSO need a Droplr password or DROPLR_TOKEN.") from exc
        raise UploadError(f"HTTP {exc.code} {detail}") from exc
    try:
        drop = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise UploadError(short(raw.decode("utf-8", "replace"), 200)) from exc
    link = next((drop.get(k) for k in ("shortlink", "shortLink", "short_link") if drop.get(k)), "")
    if not str(link).startswith("http"):
        raise UploadError(f"Droplr answered without a shortlink (fields: {', '.join(sorted(drop))})")
    return str(link).replace("http://", "https://", 1)


def _run_label(run_dir: Path) -> str:
    source = ((read_json(run_dir / "cases.json", None) or {}).get("source") or {}).get("path")
    return Path(source).stem if source else run_dir.parent.name


def _gdrive_prepare(run_dir: Path, opts: dict) -> dict:
    from . import gdrive

    gdrive.access_token(interactive=True)          # first time: browser sign-in
    label = _run_label(run_dir)
    root = gdrive.ensure_folder(gdrive.ROOT_FOLDER)
    sheet = gdrive.ensure_folder(label, root["id"])
    folder = gdrive.ensure_folder(run_dir.name, sheet["id"])
    where = f"{gdrive.ROOT_FOLDER}/{label}/{run_dir.name}"
    if opts.get("share") and opts["share"] != "none":
        info(f"Drive folder {where} shared with {gdrive.share(folder['id'], opts['share'])} (reader): "
             f"{folder.get('webViewLink')}")
    else:
        info(f"Drive folder {where} is private: links open for you and whoever this folder (or a parent) is "
             f"shared with - share it once with your team: {folder.get('webViewLink')}")
    return {"folder_id": folder["id"], "folder_link": folder.get("webViewLink")}


def _gdrive(path: Path, opts: dict) -> str:
    from . import gdrive

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        return gdrive.upload_file(path, opts["folder_id"], f"{path.parent.name}-{path.name}", mime)
    except gdrive.DriveError as exc:
        raise UploadError(str(exc)) from exc


RCLONE_REMOTE = os.environ.get("RNSMOKE_RCLONE_REMOTE", "rnsmoke-gdrive")


def _rclone_cmd(args: List[str], timeout: int = 300):
    """Run rclone and return (exit code, stdout, stderr). Patched in tests."""
    binary = shutil.which("rclone")
    if not binary:
        raise UserError("rclone is not installed: brew install rclone  (or https://rclone.org/install/)")
    res = run([binary, *args], timeout=timeout)
    return res.returncode, res.stdout, res.stderr


def rclone_remote_ready(remote: str = RCLONE_REMOTE) -> bool:
    """True only for a remote that finished sign-in (an interrupted setup leaves one without a token)."""
    code, out, _ = _rclone_cmd(["config", "dump"], timeout=30)
    if code != 0:
        return False
    try:
        return bool((json.loads(out or "{}").get(remote) or {}).get("token"))
    except ValueError:
        return False


def _rclone_stat(target: str) -> dict:
    code, out, err = _rclone_cmd(["lsjson", "--stat", "--no-mimetype", target], timeout=120)
    if code != 0:
        raise UploadError(f"rclone lsjson failed: {short(err or out, 200)}")
    return json.loads(out or "{}")


def _rclone_prepare(run_dir: Path, opts: dict) -> dict:
    remote = opts.get("remote") or RCLONE_REMOTE
    if not rclone_remote_ready(remote):
        raise UserError(f"rclone remote '{remote}:' is not set up yet. Run once: rnsmoke rclone-setup "
                        "(signs in to Google Drive in the browser; no admin needed)")
    folder = f"{ROOT_DRIVE_FOLDER}/{_run_label(run_dir)}/{run_dir.name}"
    code, out, err = _rclone_cmd(["mkdir", f"{remote}:{folder}"], timeout=120)
    if code != 0:
        raise UploadError(f"rclone mkdir failed: {short(err or out, 200)}")
    folder_id = _rclone_stat(f"{remote}:{folder}").get("ID")
    folder_link = f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else folder
    share = opts.get("share") or "none"
    if share == "domain":
        raise UserError("rclone cannot share with a domain: share the folder in Google Drive, or use --share anyone")
    if share == "anyone":
        code, out, err = _rclone_cmd(["link", f"{remote}:{folder}"], timeout=120)
        if code != 0:
            raise UploadError(f"rclone link failed: {short(err or out, 200)}")
        info(f"Drive folder {folder} shared with anyone who has the link: {out.strip()}")
    else:
        info(f"Drive folder {folder} is private: links open for you and whoever the folder (or a parent) is "
             f"shared with - share it once with your team: {folder_link}")
    return {"remote": remote, "folder": folder, "folder_link": folder_link}


def _rclone_upload(path: Path, opts: dict) -> str:
    target = f"{opts['remote']}:{opts['folder']}/{path.parent.name}-{path.name}"
    code, out, err = _rclone_cmd(["copyto", str(path), target], timeout=600)
    if code != 0:
        raise UploadError(f"rclone copyto failed: {short(err or out, 200)}")
    file_id = _rclone_stat(target).get("ID")
    if not file_id:
        raise UploadError("rclone did not report a Drive file ID")
    return f"https://drive.google.com/file/d/{file_id}/view"


HOSTS: Dict[str, Host] = {
    "gdrive": Host("gdrive", "Google Drive with the team's own OAuth client (recommended) - private by default in "
                             "'RN smoke evidence/<sheet>/<run>'; rnsmoke only sees files it created (drive.file); "
                             "--share domain|anyone shares the run folder; one-time `rnsmoke drive-login`",
                   _gdrive, 5120, prepare=_gdrive_prepare),
    "rclone": Host("rclone", "Google Drive via rclone - same folder layout; rclone's shared Google client is being "
                             "retired in 2026, so give rclone your own client; one-time `rnsmoke rclone-setup`",
                   _rclone_upload, 5120, prepare=_rclone_prepare),
    "droplr": Host("droplr", "d.pr (Droplr) - EXPERIMENTAL, based on the old droplr-js SDK (unverified); links "
                             "follow the account's privacy settings; needs DROPLR_USERNAME + DROPLR_PASSWORD "
                             "(or DROPLR_TOKEN), optional DROPLR_BOARD", _droplr, 2048),
    "catbox": Host("catbox", "catbox.moe - permanent public links, no account, images + videos up to 200 MB "
                             "(set CATBOX_USERHASH to manage/delete them from a catbox account)", _catbox, 200),
    "litterbox": Host("litterbox", "litterbox.catbox.moe - temporary links that self-delete after "
                                   "1h / 12h / 24h / 72h (--expire), up to 1 GB", _litterbox, 1000),
    "imgbb": Host("imgbb", "imgbb.com - images only, free API key in IMGBB_API_KEY, optional --expire "
                           "(e.g. 30d); videos keep their local link", _imgbb, 32, images_only=True),
}


def parse_duration(value: str) -> int:
    match = re.match(r"^(\d+)\s*([mhd])$", str(value).strip().lower())
    if not match:
        raise UserError(f"Bad duration '{value}' (use e.g. 90m, 72h, 30d)")
    amount, unit = int(match.group(1)), match.group(2)
    return amount * {"m": 60, "h": 3600, "d": 86400}[unit]


# --------------------------------------------------------------------------- run evidence

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _expired(entry: dict) -> bool:
    expires = entry.get("expires_at")
    if not expires:
        return False
    try:
        return dt.datetime.fromisoformat(expires) <= dt.datetime.now().astimezone() + dt.timedelta(minutes=10)
    except ValueError:
        return True


def evidence_files(runs: List[dict]) -> List[str]:
    """Run-relative paths of every screenshot / video referenced by the results."""
    found = set()
    for run_doc in runs:
        for record in (run_doc.get("results") or {}).values():
            for key in ("evidence", "video"):
                if record.get(key):
                    found.add(record[key])
    return sorted(found)


def plan_uploads(run_dir: Path, runs: List[dict], host: str) -> List[dict]:
    """What `upload_evidence` would publish, without touching the network (for --dry-run)."""
    if host not in HOSTS:
        raise UserError(f"Unknown host '{host}'. Choose one of: {', '.join(HOSTS)}")
    spec = HOSTS[host]
    cache = (read_json(run_dir / CACHE_FILE, None) or {}).get("files", {})
    plan = []
    for rel in evidence_files(runs):
        path = run_dir / rel
        if not path.is_file():
            plan.append({"file": rel, "action": "skip (missing)", "bytes": 0})
            continue
        size = path.stat().st_size
        entry = cache.get(rel) or {}
        if spec.images_only and path.suffix.lower() not in IMAGE_SUFFIXES:
            action = "skip (images only)"
        elif size > spec.max_mb * 1024 * 1024:
            action = f"skip (> {spec.max_mb} MB)"
        elif entry.get("host") == host and entry.get("sha256") == _sha256(path) and not _expired(entry):
            action = f"reuse {entry['url']}"
        else:
            action = "upload"
        plan.append({"file": rel, "action": action, "bytes": size})
    return plan


def upload_evidence(run_dir: Path, runs: List[dict], host: str, expire: Optional[str] = None,
                    force: bool = False, retries: int = 2, share: Optional[str] = None) -> Dict[str, str]:
    """Upload the evidence of a run (cached) and return {run-relative path: URL}."""
    if host not in HOSTS:
        raise UserError(f"Unknown host '{host}'. Choose one of: {', '.join(HOSTS)}")
    spec = HOSTS[host]
    if share and share != "none" and host not in ("gdrive", "rclone"):
        raise UserError("--share applies to --host rclone / gdrive only")
    if host in ("catbox", "droplr", "gdrive", "rclone") and expire:
        raise UserError(f"--expire is not supported for {host} (use the host's own settings, or litterbox / imgbb)")
    if host == "litterbox" and (expire or "72h") not in LITTERBOX_TIMES:
        raise UserError(f"litterbox keeps files for {', '.join(LITTERBOX_TIMES)} only")
    expire = expire or ("72h" if host == "litterbox" else None)
    lifetime = parse_duration(expire) if expire else None

    cache_path = run_dir / CACHE_FILE
    cache = read_json(cache_path, None) or {"version": 1, "files": {}}
    links: Dict[str, str] = {}
    counts = {"uploaded": 0, "reused": 0, "skipped": 0, "failed": 0}
    opts = {"expire": expire, "share": share}
    prepared = spec.prepare is None
    for rel in evidence_files(runs):
        path = run_dir / rel
        if not path.is_file():
            warn(f"evidence missing on disk, keeping the local link: {rel}")
            counts["skipped"] += 1
            continue
        if spec.images_only and path.suffix.lower() not in IMAGE_SUFFIXES:
            counts["skipped"] += 1
            continue
        if path.stat().st_size > spec.max_mb * 1024 * 1024:
            warn(f"{rel} is larger than {spec.max_mb} MB ({host}); keeping the local link")
            counts["skipped"] += 1
            continue
        digest = _sha256(path)
        entry = cache["files"].get(rel)
        if (entry and not force and entry.get("sha256") == digest and entry.get("host") == host
                and entry.get("expire") == expire and not _expired(entry)):
            links[rel] = entry["url"]
            counts["reused"] += 1
            continue
        if not prepared:
            try:
                opts.update(spec.prepare(run_dir, opts))
                prepared = True
            except UserError:
                raise
            except Exception as exc:  # noqa: BLE001 - any network/API failure: keep local links
                warn(f"{host} is not reachable ({short(exc, 200)}); keeping local links")
                counts["failed"] += 1
                break
        url, error = None, None
        for attempt in range(retries + 1):
            try:
                url = spec.upload(path, opts)
                break
            except UserError:
                raise
            except (urllib.error.URLError, OSError, UploadError, ValueError) as exc:
                error = exc
                if attempt < retries:
                    time.sleep(min(10, 2 ** attempt))
        if not url:
            warn(f"upload failed for {rel} ({short(error, 160)}); keeping the local link")
            counts["failed"] += 1
            continue
        uploaded_at = dt.datetime.now().astimezone()
        cache["files"][rel] = {
            "url": url, "host": host, "sha256": digest, "expire": expire, "uploaded_at": now_iso(),
            "expires_at": (uploaded_at + dt.timedelta(seconds=lifetime)).isoformat(timespec="seconds")
            if lifetime else None,
        }
        write_json(cache_path, cache)       # save as we go: an interrupted upload resumes from here
        links[rel] = url
        counts["uploaded"] += 1
        info(f"  {rel} -> {url}")
    info(f"Evidence on {host}: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v)
         + (f" (links expire after {expire})" if expire else ""))
    return links
