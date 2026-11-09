"""Google sign-in (OAuth), encrypted token storage and a tiny Calendar API client (stdlib HTTP only).
The OAuth client and token are never logged; they live encrypted in data/, keyed by SKYBOLT_SECRET_KEY
from .env or, if that is unset, by data/secret.key (created on first use)."""
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


class GoogleError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def urllib_http(method: str, url: str, headers: dict | None = None, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


class Google:
    def __init__(self, settings: Settings, http=urllib_http):
        self.s, self.http = settings, http
        data = settings.db_path.parent
        self.token_path, self.client_path, self.key_path = (
            data / "google_token.enc", data / "google_client.enc", data / "secret.key")
        self._token: dict | None = None

    # ---- encrypted files in data/ -----------------------------------------
    def _fernet(self) -> Fernet:
        key = self.s.secret_key
        if not key:  # no key in .env: make one on first use, readable only by us
            if not self.key_path.exists():
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            key = self.key_path.read_text().strip()
        return Fernet(key.encode())

    def _read(self, path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(self._fernet().decrypt(path.read_bytes()))
        except (InvalidToken, ValueError):
            return None

    def _write(self, path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(self._fernet().encrypt(json.dumps(data).encode()))
        tmp.replace(path)

    # ---- setup -------------------------------------------------------------
    def problem(self) -> str | None:
        """Something broken in the setup, or None."""
        try:
            self._fernet()
        except ValueError:
            return "SKYBOLT_SECRET_KEY in .env is not a valid key"
        return None

    def client(self) -> dict | None:
        """The OAuth client pasted in Settings, else a credentials.json file if there is one."""
        if self.problem():
            return None
        c = self._read(self.client_path)
        if c:
            return c
        try:
            raw = json.loads(self.s.google_credentials.read_text())
            c = raw.get("web") or raw["installed"]
            uris = [u for u in c.get("redirect_uris", []) if u.endswith("/api/google/callback")]
            return {"id": c["client_id"], "secret": c["client_secret"], "redirect": uris[0] if uris else None}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def save_client(self, client_id: str, secret: str) -> None:
        self._write(self.client_path, {"id": client_id, "secret": secret})
        self.clear_token()  # a token belongs to the client that made it

    # ---- token storage -----------------------------------------------------
    def token(self) -> dict | None:
        if self._token is None and not self.problem():
            self._token = self._read(self.token_path)
        return self._token

    def connected(self) -> bool:
        return self.client() is not None and self.token() is not None

    def save_token(self, t: dict) -> None:
        self._write(self.token_path, t)
        self._token = t

    def clear_token(self) -> None:
        self.token_path.unlink(missing_ok=True)
        self._token = None

    # ---- OAuth -------------------------------------------------------------
    def auth_url(self, state: str, verifier: str, redirect: str) -> str:
        c = self.client()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": c["id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})

    def _token_request(self, form: dict) -> dict:
        status, raw = self.http("POST", TOKEN_URL, FORM, urllib.parse.urlencode(form).encode())
        data = _json(raw)
        if status != 200:
            raise GoogleError(status, data.get("error_description") or data.get("error") or "token request failed")
        return data

    def exchange(self, code: str, verifier: str, redirect: str) -> None:
        c = self.client()
        t = self._token_request({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                 "client_id": c["id"], "client_secret": c["secret"], "redirect_uri": redirect})
        if "refresh_token" not in t:
            raise GoogleError(400, "Google did not return a refresh token")
        self.save_token({"refresh_token": t["refresh_token"], "access_token": t["access_token"],
                         "expires_at": time.time() + t.get("expires_in", 3600)})

    def revoke(self) -> None:
        t = self.token()
        if t:
            try:
                self.http("POST", REVOKE_URL, FORM, urllib.parse.urlencode({"token": t["refresh_token"]}).encode())
            except OSError:
                pass  # offline: the local token is deleted anyway

    def access_token(self) -> str:
        t = self.token()
        if not t or not self.client():
            raise GoogleError(401, "Google is not connected")
        if t.get("expires_at", 0) - 60 < time.time():
            c = self.client()
            try:
                n = self._token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                         "client_id": c["id"], "client_secret": c["secret"]})
            except GoogleError as e:
                if e.status in (400, 401):
                    raise GoogleError(401, "Google sign-in expired or was revoked. Disconnect and connect again.")
                raise
            t = {**t, "access_token": n["access_token"], "expires_at": time.time() + n.get("expires_in", 3600)}
            self.save_token(t)
        return t["access_token"]

    # ---- Calendar API ------------------------------------------------------
    def api(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        status, raw = self.http(method, url, headers, data)
        payload = _json(raw)
        if status >= 400:
            err = payload.get("error")
            raise GoogleError(status, (err.get("message") if isinstance(err, dict) else None) or f"Google API error {status}")
        return payload
