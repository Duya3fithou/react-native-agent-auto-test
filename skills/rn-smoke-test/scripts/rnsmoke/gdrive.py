"""Google Drive storage for evidence (standard library only).

Security model
  * OAuth scope `drive.file`: the tool can only see/modify files it created itself - never the rest of
    the user's Drive.
  * One browser login per machine (installed-app flow, PKCE, loopback redirect). The refresh token is
    stored in ~/.rnsmoke/google-token.json (chmod 600); no password ever touches a file or a prompt.
  * Nothing is shared by default: files land in "RN smoke evidence/<sheet>/<run>" in the user's Drive
    and open for the owner and whoever that folder is shared with. `share="domain"` / `"anyone"`
    adds a reader permission on the run folder only.

Google requires every app that asks for a token to have its own registered OAuth client. An admin
creates one "Desktop app" client once (Drive API enabled, consent screen "Internal" so only company
accounts can sign in). Lookup order: RNSMOKE_GOOGLE_CLIENT_ID / _SECRET, RNSMOKE_GOOGLE_CLIENT_FILE,
~/.rnsmoke/google-oauth-client.json, the client bundled with the skill
(skills/rn-smoke-test/google-oauth-client.json), then <repo>/resource/client_secret_*.json as downloaded
from the Cloud Console. Repo copies are git-ignored; commit one deliberately (git add -f) only to the
company's private repo - Google does not treat desktop-app client secrets as confidential. Each person's
token stays on their own machine.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Dict, Optional, Tuple

from .util import UserError, info, short

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER = "RN smoke evidence"
HOME = Path(os.environ.get("RNSMOKE_HOME", Path.home() / ".rnsmoke"))
TOKEN_FILE = HOME / "google-token.json"
CLIENT_FILE = HOME / "google-oauth-client.json"
BUNDLED_CLIENT = Path(__file__).resolve().parents[2] / "google-oauth-client.json"
RESOURCE_DIR = Path(__file__).resolve().parents[4] / "resource"     # <repo>/resource/client_secret_*.json


class DriveError(Exception):
    """A Drive API call failed (the caller keeps the local link)."""


# --------------------------------------------------------------------------- HTTP

def _http(method: str, url: str, body: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
          timeout: int = 180) -> Tuple[int, Dict[str, str], bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        finally:
            exc.close()
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, payload


def _form(url: str, fields: Dict[str, str]) -> dict:
    status, _, raw = _http("POST", url, urllib.parse.urlencode(fields).encode(),
                           {"Content-Type": "application/x-www-form-urlencoded"})
    data = json.loads(raw.decode("utf-8", "replace") or "{}")
    if status >= 400:
        raise UserError(f"Google sign-in failed ({status}): {short(data.get('error_description') or data, 200)}")
    return data


# --------------------------------------------------------------------------- OAuth

def _read_client(path: Path) -> Tuple[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise UserError(f"{path} is not valid JSON") from exc
    block = data.get("installed") or data.get("web") or data
    if not block.get("client_id") or not block.get("client_secret"):
        raise UserError(f"{path} is not an OAuth client JSON (missing client_id / client_secret)")
    return block["client_id"], block["client_secret"]


def load_client() -> Tuple[str, str]:
    client_id = os.environ.get("RNSMOKE_GOOGLE_CLIENT_ID")
    secret = os.environ.get("RNSMOKE_GOOGLE_CLIENT_SECRET")
    if client_id and secret:
        return client_id, secret
    explicit = os.environ.get("RNSMOKE_GOOGLE_CLIENT_FILE")
    in_repo = sorted(RESOURCE_DIR.glob("client_secret_*.json")) if RESOURCE_DIR.is_dir() else []
    candidates = ([Path(explicit).expanduser()] if explicit else []) + [CLIENT_FILE, BUNDLED_CLIENT] + in_repo
    for path in candidates:
        if path.exists():
            return _read_client(path)
    raise UserError("No Google OAuth client configured. Get the company's 'Desktop app' client JSON from your "
                    "admin and run: rnsmoke drive-login --client-file <file.json>  (README: Google Drive)")


def import_client(path: Path) -> Path:
    """Validate a downloaded client JSON and store it as ~/.rnsmoke/google-oauth-client.json (chmod 600)."""
    path = Path(path).expanduser()
    if not path.exists():
        raise UserError(f"Client file not found: {path}")
    _read_client(path)
    HOME.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(CLIENT_FILE, 0o600)
    return CLIENT_FILE


def pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state,
    })


def _save_token(data: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)


def login(open_browser: bool = True, timeout: int = 300) -> dict:
    """Browser sign-in; stores the refresh token. Returns the token record."""
    client_id, secret = load_client()
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    received: Dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" in query or "error" in query:
                received.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h3>rnsmoke: Google Drive connected. You can close this tab.</h3>".encode())

        def log_message(self, *args):  # silence the default stderr logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    url = auth_url(client_id, redirect_uri, challenge, state)
    info("Sign in to Google in the browser to let rnsmoke store evidence in your Drive (scope: drive.file).")
    info(f"If no browser opens, visit:\n{url}")
    if open_browser:
        webbrowser.open(url)
    deadline = time.time() + timeout
    server.timeout = 2
    try:
        while not received and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not received:
        raise UserError("Google sign-in timed out")
    if received.get("error") or received.get("state") != state:
        raise UserError(f"Google sign-in was not completed: {received.get('error') or 'state mismatch'}")
    token = _form(TOKEN_URL, {"code": received["code"], "client_id": client_id, "client_secret": secret,
                              "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                              "code_verifier": verifier})
    if not token.get("refresh_token"):
        raise UserError("Google did not return a refresh token; remove the app's access at "
                        "https://myaccount.google.com/permissions and sign in again")
    record = {"refresh_token": token["refresh_token"], "access_token": token.get("access_token"),
              "expires_at": time.time() + int(token.get("expires_in", 0)), "client_id": client_id,
              "scope": token.get("scope", SCOPE)}
    _save_token(record)
    try:
        email = (about(record).get("user") or {}).get("emailAddress", "?")
    except DriveError as exc:
        email = "?"
        info(f"Signed in, but the Drive API answered: {short(exc, 300)}\n"
             "If it says the API is disabled, enable 'Google Drive API' in the client's Cloud project.")
    record["account"] = email
    _save_token(record)
    info(f"Google Drive connected as {email}; token saved to {TOKEN_FILE}")
    return record


def find_downloaded_client() -> Optional[Path]:
    """The newest client_secret_*.json in ~/Downloads (Google's default name for a downloaded client)."""
    found = sorted((Path.home() / "Downloads").glob("client_secret_*.json"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _token(interactive: bool) -> dict:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    if not interactive:
        raise UserError("Not signed in to Google Drive. Run: rnsmoke drive-login")
    return login()


def access_token(interactive: bool = True, force_refresh: bool = False) -> str:
    record = _token(interactive)
    if not force_refresh and record.get("access_token") and record.get("expires_at", 0) > time.time() + 60:
        return record["access_token"]
    client_id, secret = load_client()
    data = _form(TOKEN_URL, {"client_id": client_id, "client_secret": secret,
                             "refresh_token": record["refresh_token"], "grant_type": "refresh_token"})
    record.update(access_token=data["access_token"], expires_at=time.time() + int(data.get("expires_in", 3600)))
    _save_token(record)
    return record["access_token"]


# --------------------------------------------------------------------------- Drive API

def _api(method: str, url: str, body: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
         token: Optional[str] = None) -> Tuple[Dict[str, str], dict]:
    for attempt in (0, 1):
        auth = {"Authorization": f"Bearer {token or access_token(force_refresh=attempt == 1)}"}
        status, resp_headers, raw = _http(method, url, body, {**auth, **(headers or {})})
        if status == 401 and attempt == 0 and token is None:
            continue                                         # expired access token: refresh once
        text = raw.decode("utf-8", "replace")
        if status >= 400:
            raise DriveError(f"Drive API {status}: {short(text, 240)}")
        return resp_headers, (json.loads(text) if text.strip() else {})
    raise DriveError("Drive API: unauthorized")


def about(record: Optional[dict] = None) -> dict:
    _, data = _api("GET", f"{DRIVE}/about?fields=user(emailAddress,displayName)",
                   token=(record or {}).get("access_token"))
    return data


def _quote(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def ensure_folder(name: str, parent: Optional[str] = None) -> dict:
    """Find (among files this app created) or create a folder; returns {id, webViewLink}."""
    query = f"name = '{_quote(name)}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    query += f" and '{parent}' in parents" if parent else " and 'root' in parents"
    _, found = _api("GET", f"{DRIVE}/files?" + urllib.parse.urlencode(
        {"q": query, "fields": "files(id,name,webViewLink)", "spaces": "drive"}))
    if found.get("files"):
        return found["files"][0]
    metadata = {"name": name, "mimeType": FOLDER_MIME, **({"parents": [parent]} if parent else {})}
    _, created = _api("POST", f"{DRIVE}/files?fields=id,webViewLink", json.dumps(metadata).encode(),
                      {"Content-Type": "application/json; charset=UTF-8"})
    return created


def share(folder_id: str, mode: str) -> str:
    """Add a reader permission on a folder: 'domain' (the account's Workspace domain) or 'anyone'."""
    if mode == "anyone":
        permission = {"type": "anyone", "role": "reader"}
        target = "anyone with the link"
    elif mode == "domain":
        email = (about().get("user") or {}).get("emailAddress", "")
        domain = email.split("@")[-1].lower()
        if not domain or domain in ("gmail.com", "googlemail.com"):
            raise UserError("--share domain needs a Google Workspace account (got a personal Gmail account)")
        permission = {"type": "domain", "role": "reader", "domain": domain}
        target = f"everyone at {domain}"
    else:
        raise UserError(f"Unknown share mode '{mode}' (none | domain | anyone)")
    _api("POST", f"{DRIVE}/files/{folder_id}/permissions", json.dumps(permission).encode(),
         {"Content-Type": "application/json; charset=UTF-8"})
    return target


def upload_file(path: Path, folder_id: str, name: str, mime: str) -> str:
    """Resumable upload (works for screenshots and large videos alike); returns the webViewLink."""
    metadata = json.dumps({"name": name, "parents": [folder_id]}).encode()
    data = path.read_bytes()
    headers, _ = _api("POST", f"{UPLOAD}/files?uploadType=resumable&fields=id,webViewLink", metadata,
                      {"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": mime,
                       "X-Upload-Content-Length": str(len(data))})
    session = headers.get("location")
    if not session:
        raise DriveError("Drive did not return an upload session")
    status, _, raw = _http("PUT", session, data, {"Content-Type": mime})
    text = raw.decode("utf-8", "replace")
    if status >= 400:
        raise DriveError(f"Drive upload {status}: {short(text, 240)}")
    created = json.loads(text) if text.strip() else {}
    link = created.get("webViewLink") or (f"https://drive.google.com/file/d/{created['id']}/view"
                                          if created.get("id") else "")
    if not link.startswith("https://"):
        raise DriveError(f"Drive upload returned no link: {short(text, 160)}")
    return link
