import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .google import GoogleError
from .gsync import WRITABLE, forget_calendar_events

router = APIRouter(prefix="/api/google", tags=["google"])
STATE_TTL = 600
LOOPBACK = ("127.0.0.1", "localhost", "::1")


class ClientIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(min_length=1, max_length=300)


class CalendarToggle(BaseModel):
    enabled: bool


@router.get("/status")
def status(request: Request):
    st = request.app.state
    cals = [{"id": r["id"], "summary": r["summary"], "color": r["color"], "enabled": bool(r["enabled"]),
             "writable": r["access_role"] in WRITABLE, "primary": bool(r["is_primary"])}
            for r in st.db.execute("SELECT * FROM google_calendars ORDER BY is_primary DESC, summary")]
    return {"problem": st.google.problem(), "has_client": st.google.client() is not None,
            "connected": st.google.connected(),
            "account": next((c["id"] for c in cals if c["primary"]), None), "calendars": cals, **st.syncer.status}


@router.post("/client")
def set_client(request: Request, body: ClientIn):
    """The Client ID and secret from the Google Cloud console, pasted in Settings."""
    cid, secret = body.client_id.strip(), body.client_secret.strip()
    if not cid.endswith(".apps.googleusercontent.com"):
        raise HTTPException(400, "That doesn't look like a Client ID (it ends in .apps.googleusercontent.com)")
    with request.app.state.syncer.lock:
        request.app.state.google.save_client(cid, secret)
    return status(request)


@router.get("/connect")
def connect(request: Request):
    st = request.app.state
    c = st.google.client()
    if not c:
        raise HTTPException(400, st.google.problem() or "Add your Google Client ID first")
    if not c.get("redirect") and request.url.hostname not in LOOPBACK:
        raise HTTPException(400, "Connect from the Pi itself: open http://localhost:8000 in its browser")
    redirect = c.get("redirect") or f"{request.url.scheme}://{request.url.netloc}/"  # desktop-app clients: any loopback
    now = time.time()
    st.oauth_pending = {k: v for k, v in st.oauth_pending.items() if now - v[1] < STATE_TTL}
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    st.oauth_pending[state] = (verifier, now, redirect)
    return RedirectResponse(st.google.auth_url(state, verifier, redirect), 303)


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    return finish_sign_in(request, state, code, error)


def finish_sign_in(request: Request, state: str, code: str, error: str) -> RedirectResponse:
    """Google sends the browser back here (or to "/") after sign-in."""
    st = request.app.state
    pending = st.oauth_pending.pop(state, None)
    if error or not code or not pending or time.time() - pending[1] > STATE_TTL:
        st.syncer.status["error"] = f"Google sign-in did not finish ({error or 'expired, try again'})"
    else:
        try:
            st.google.exchange(code, pending[0], pending[2])
            st.syncer.status["error"] = None
            st.syncer.sync()
        except (GoogleError, OSError) as e:
            st.syncer.status["error"] = f"Google sign-in failed: {e}"
    return RedirectResponse("/?open=settings", 303)


@router.post("/disconnect", status_code=204)
def disconnect(request: Request):
    st = request.app.state
    with st.syncer.lock:
        st.google.revoke()
        st.google.clear_token()
        st.db.execute("DELETE FROM events WHERE calendar_id IN (SELECT id FROM google_calendars)")
        st.db.execute("DELETE FROM google_calendars")
        st.db.commit()
    st.syncer.status.update(last_sync=None, error=None)


@router.put("/calendars/{cal_id:path}")
def set_calendar(request: Request, cal_id: str, body: CalendarToggle):
    st = request.app.state
    with st.syncer.lock:
        if st.db.execute("UPDATE google_calendars SET enabled=? WHERE id=?", (int(body.enabled), cal_id)).rowcount == 0:
            raise HTTPException(404, "calendar not found")
        if not body.enabled:
            forget_calendar_events(st.db, cal_id)
        st.db.commit()
    if body.enabled:
        st.syncer.sync()
    return status(request)


@router.post("/sync")
def sync_now(request: Request):
    request.app.state.syncer.sync()
    return status(request)
