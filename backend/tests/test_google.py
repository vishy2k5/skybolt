import json
import sqlite3
import time
import urllib.parse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.main import create_app

PRIMARY, FAMILY, HOLIDAYS = "me@example.com", "family#abc@group.calendar.google.com", "holidays@group.v.calendar.google.com"


class FakeGoogle:
    """Just enough of Google's OAuth + Calendar API, with sync tokens."""

    def __init__(self):
        self.calendars = [
            {"id": PRIMARY, "summary": PRIMARY, "primary": True, "accessRole": "owner", "backgroundColor": "#9fe1e7"},
            {"id": FAMILY, "summary": "Family", "accessRole": "writer", "backgroundColor": "#f691b2"},
            {"id": HOLIDAYS, "summary": "Holidays", "accessRole": "reader", "backgroundColor": "#16a765"},
        ]
        self.events = {c["id"]: {} for c in self.calendars}
        self.seq, self.changed, self.n = 0, {}, 0
        self.page_size, self.fail_writes, self.calls = 2, None, []

    def put(self, cal, item):
        self.seq += 1
        item = {"status": "confirmed", "etag": f'"{self.seq}"', **item}
        self.events[cal][item["id"]] = item
        self.changed[(cal, item["id"])] = self.seq
        return item

    def __call__(self, method, url, headers=None, data=None):
        u = urllib.parse.urlsplit(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.calls.append((method, u.path))
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = dict(urllib.parse.parse_qsl(data.decode()))
            if form["grant_type"] == "authorization_code":
                if form["code"] != "good" or not form.get("code_verifier"):
                    return 400, b'{"error": "invalid_grant"}'
                return 200, json.dumps({"access_token": "at1", "refresh_token": "rt-secret", "expires_in": 3600}).encode()
            return 200, json.dumps({"access_token": "at2", "expires_in": 3600}).encode()
        if url.startswith("https://oauth2.googleapis.com/revoke"):
            return 200, b""
        assert headers["Authorization"].startswith("Bearer at")
        path = u.path.removeprefix("/calendar/v3")
        if path == "/users/me/calendarList":
            return 200, json.dumps({"items": self.calendars}).encode()
        parts = path.split("/")  # ['', 'calendars', cal, 'events', id?]
        cal = urllib.parse.unquote(parts[2])
        eid = urllib.parse.unquote(parts[4]) if len(parts) > 4 else None
        if method == "GET":
            return self._list(cal, q)
        if self.fail_writes or cal == HOLIDAYS:
            return self.fail_writes or 403, b'{"error": {"message": "Forbidden"}}'
        body = json.loads(data) if data else None
        if method == "POST":
            self.n += 1
            return 200, json.dumps(self.put(cal, {**body, "id": f"new{self.n}"})).encode()
        if eid not in self.events[cal]:
            return 404, b'{"error": {"message": "Not Found"}}'
        if method == "PATCH":
            return 200, json.dumps(self.put(cal, {**self.events[cal][eid], **body})).encode()
        if method == "DELETE":
            self.put(cal, {**self.events[cal][eid], "status": "cancelled"})
            return 204, b""
        raise AssertionError(method)

    def _list(self, cal, q):
        assert q["showDeleted"] == "true" and "singleEvents" not in q
        since = 0
        if "syncToken" in q:
            if q["syncToken"] == "expired":
                return 410, b'{"error": {"message": "Gone"}}'
            since = int(q["syncToken"])
        items = [e for (c, i), s in sorted(self.changed.items(), key=lambda x: x[1])
                 if c == cal and s > since for e in [self.events[c][i]]]
        if not since:  # a full sync has nothing to say about deleted one-off events
            items = [e for e in items if e["status"] != "cancelled" or e.get("recurringEventId")]
        off = int(q.get("pageToken", 0))
        page = {"items": items[off:off + self.page_size]}
        if off + self.page_size < len(items):
            page["nextPageToken"] = str(off + self.page_size)
        else:
            page["nextSyncToken"] = str(self.seq)
        return 200, json.dumps(page).encode()


@pytest.fixture(autouse=True)
def denver(monkeypatch):
    monkeypatch.setenv("TZ", "America/Denver")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


CLIENT = {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-shh"}


def make(tmp_path, fake, key="", creds=None):
    s = Settings(db_path=tmp_path / "data" / "t.db", host="127.0.0.1", port=8000, ui_dir=tmp_path / "none",
                 secret_key=key, google_credentials=creds or tmp_path / "credentials.json",
                 timezone="America/Denver", google_sync_seconds=0)
    return TestClient(create_app(s, google_http=fake), base_url="http://127.0.0.1:8000", follow_redirects=False)


def sign_in(c):
    r = c.get("/api/google/connect")
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers["location"]).query)["state"][0]
    return c.get("/", params={"state": state, "code": "good"})


@pytest.fixture
def fake():
    return FakeGoogle()


@pytest.fixture
def gc(tmp_path, fake):
    with make(tmp_path, fake) as c:
        c.post("/api/google/client", json=CLIENT)
        assert sign_in(c).status_code == 303
        c.sync = lambda: c.post("/api/google/sync").json()
        yield c


def week(c, start="2026-11-01", end="2026-11-30"):
    return c.get("/api/events", params={"start": f"{start}T00:00:00", "end": f"{end}T00:00:00"}).json()


def test_needs_client(tmp_path, fake):
    with make(tmp_path, fake) as c:
        st = c.get("/api/google/status").json()
        assert st["problem"] is None and not st["has_client"] and not st["connected"]
        assert "Client ID" in c.get("/api/google/connect").json()["detail"]
        bad = c.post("/api/google/client", json={**CLIENT, "client_id": "oops"})
        assert bad.status_code == 400
        assert c.post("/api/google/client", json=CLIENT).json()["has_client"]
        r = c.get("http://192.168.1.20:8000/api/google/connect")  # from a phone: Google needs the Pi's own browser
        assert r.status_code == 400 and "localhost" in r.json()["detail"]
    with make(tmp_path, fake, key="not-a-key") as c:
        assert "SKYBOLT_SECRET_KEY" in c.get("/api/google/status").json()["problem"]


def test_client_and_token_are_encrypted(tmp_path, fake):
    with make(tmp_path, fake) as c:
        c.post("/api/google/client", json=CLIENT)
        sign_in(c)
    data = tmp_path / "data"
    assert (data / "secret.key").stat().st_mode & 0o777 == 0o600
    for name in ("google_client.enc", "google_token.enc"):
        raw = (data / name).read_bytes()
        assert b"GOCSPX" not in raw and b"rt-secret" not in raw
    with make(tmp_path, fake) as c:  # survives a restart with the generated key
        assert c.get("/api/google/status").json()["connected"]


def test_web_client_file_still_works(tmp_path, fake):
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"web": {"client_id": "cid", "client_secret": "s",
                                         "redirect_uris": ["http://localhost:8000/api/google/callback"]}}))
    with make(tmp_path, fake, key=Fernet.generate_key().decode(), creds=creds) as c:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(c.get("/api/google/connect").headers["location"]).query)
        assert q["redirect_uri"] == ["http://localhost:8000/api/google/callback"]


def test_connect_flow(tmp_path, fake):
    with make(tmp_path, fake) as c:
        c.post("/api/google/client", json=CLIENT)
        r = c.get("/api/google/connect")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers["location"]).query)
        assert r.headers["location"].startswith("https://accounts.google.com/")
        assert q["redirect_uri"] == ["http://127.0.0.1:8000/"] and q["client_id"] == [CLIENT["client_id"]]
        assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
        c.get("/", params={"state": "forged", "code": "good"})
        st = c.get("/api/google/status").json()
        assert not st["connected"] and "did not finish" in st["error"]
        r = c.get("/", params={"state": q["state"][0], "code": "good"})
        assert r.headers["location"] == "/?open=settings"
        st = c.get("/api/google/status").json()
        assert st["connected"] and st["account"] == PRIMARY and st["error"] is None
        assert {x["id"]: x["enabled"] for x in st["calendars"]} == {PRIMARY: True, FAMILY: False, HOLIDAYS: False}
        assert c.get("/", params={"state": q["state"][0], "code": "good"}).status_code == 303
        assert "did not finish" in c.get("/api/google/status").json()["error"]  # state can't be reused


def test_pull_and_recurrence(gc, fake):
    fake.put(PRIMARY, {"id": "a", "summary": "Dentist", "start": {"dateTime": "2026-11-10T09:00:00-07:00"},
                       "end": {"dateTime": "2026-11-10T10:00:00-07:00"}, "location": "Smile Dental"})
    fake.put(PRIMARY, {"id": "b", "summary": "Trip", "start": {"date": "2026-11-12"}, "end": {"date": "2026-11-14"}})
    fake.put(PRIMARY, {"id": "c", "summary": "Swim", "start": {"dateTime": "2026-11-02T17:00:00-07:00"},
                       "end": {"dateTime": "2026-11-02T18:00:00-07:00"}, "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"]})
    fake.put(PRIMARY, {"id": "d", "summary": "Piano", "start": {"dateTime": "2026-11-03T15:00:00-07:00"},
                       "end": {"dateTime": "2026-11-03T16:00:00-07:00"},
                       "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261113T055959Z",
                                      "EXDATE;TZID=America/Denver:20261105T150000"]})
    fake.put(PRIMARY, {"id": "d_20261110T220000Z", "recurringEventId": "d", "summary": "Piano (moved)",
                       "originalStartTime": {"dateTime": "2026-11-10T15:00:00-07:00"},
                       "start": {"dateTime": "2026-11-11T15:00:00-07:00"}, "end": {"dateTime": "2026-11-11T16:00:00-07:00"}})
    fake.put(PRIMARY, {"id": "c_20261116T000000Z", "recurringEventId": "c", "status": "cancelled",
                       "originalStartTime": {"dateTime": "2026-11-16T17:00:00-07:00"}})
    assert gc.sync()["error"] is None

    evs = week(gc)
    by = lambda t: [e["start"] for e in evs if e["title"] == t]
    assert by("Dentist") == ["2026-11-10T09:00:00"]
    trip = next(e for e in evs if e["title"] == "Trip")
    assert trip["all_day"] and trip["end"] == "2026-11-13T23:59:00"
    swim = next(e for e in evs if e["title"] == "Swim")
    assert swim["repeat"] == "weekly"  # BYDAY matching the start day is plain weekly
    assert by("Swim") == ["2026-11-02T17:00:00", "2026-11-09T17:00:00", "2026-11-23T17:00:00"]  # 16th cancelled
    assert by("Piano") == ["2026-11-03T15:00:00", "2026-11-12T15:00:00"]  # 5th excluded, 10th moved, ends 12th
    assert next(e for e in evs if e["title"] == "Piano")["repeat"] == "custom"
    assert by("Piano (moved)") == ["2026-11-11T15:00:00"]


def test_push_create_update_delete(gc, fake):
    mia = gc.post("/api/members", json={"name": "Mia"}).json()["id"]
    ev = {"title": "Soccer", "start": "2026-11-10T17:00:00", "end": "2026-11-10T18:30:00",
          "calendar_id": PRIMARY, "member_id": mia, "repeat": "weekly"}
    eid = gc.post("/api/events", json=ev).json()["id"]
    gc.sync()
    (g,) = fake.events[PRIMARY].values()
    assert g["start"] == {"dateTime": "2026-11-10T17:00:00-07:00", "timeZone": "America/Denver"}
    assert g["recurrence"] == ["RRULE:FREQ=WEEKLY"]
    assert g["extendedProperties"]["private"]["skybolt_member"] == "Mia"
    assert gc.get(f"/api/events/{eid}").json()["google_id"] == g["id"]

    gc.put(f"/api/events/{eid}", json={**ev, "title": "Soccer!", "repeat": "none", "all_day": True,
                                       "end": "2026-11-10T23:59:00"})
    gc.sync()
    g = fake.events[PRIMARY][g["id"]]
    assert g["summary"] == "Soccer!" and g["recurrence"] == []
    assert g["start"] == {"date": "2026-11-10"} and g["end"] == {"date": "2026-11-11"}
    assert gc.get(f"/api/events/{eid}").json()["member_id"] == mia  # survives the round trip

    assert gc.delete(f"/api/events/{eid}").status_code == 204
    assert gc.get(f"/api/events/{eid}").status_code == 404  # hidden before the push
    gc.sync()
    assert g["id"] and fake.events[PRIMARY][g["id"]]["status"] == "cancelled"
    assert week(gc) == []


def test_incremental_and_expired_token(gc, fake):
    fake.put(PRIMARY, {"id": "a", "summary": "One", "start": {"date": "2026-11-05"}, "end": {"date": "2026-11-06"}})
    gc.sync()
    fake.put(PRIMARY, {**fake.events[PRIMARY]["a"], "summary": "One (edited on phone)"})
    fake.put(PRIMARY, {"id": "b", "summary": "Two", "start": {"date": "2026-11-07"}, "end": {"date": "2026-11-08"}})
    gc.sync()
    assert sorted(e["title"] for e in week(gc)) == ["One (edited on phone)", "Two"]
    fake.put(PRIMARY, {**fake.events[PRIMARY]["b"], "status": "cancelled"})
    gc.sync()
    assert [e["title"] for e in week(gc)] == ["One (edited on phone)"]

    del fake.events[PRIMARY]["a"]  # vanished without a trace, then the token expires
    del fake.changed[(PRIMARY, "a")]
    db = sqlite3.connect(gc.app.state.settings.db_path)
    db.execute("UPDATE google_calendars SET sync_token='expired'"); db.commit(); db.close()
    assert gc.sync()["error"] is None
    assert week(gc) == []


def test_read_only_and_refused(gc, fake):
    gc.put(f"/api/google/calendars/{urllib.parse.quote(HOLIDAYS, safe='')}", json={"enabled": True})
    fake.put(HOLIDAYS, {"id": "h", "summary": "Thanksgiving", "start": {"date": "2026-11-26"}, "end": {"date": "2026-11-27"}})
    gc.sync()
    (h,) = week(gc)
    assert gc.put(f"/api/events/{h['id']}", json={**h, "title": "x"}).status_code == 403
    assert gc.delete(f"/api/events/{h['id']}").status_code == 403
    assert gc.post("/api/events", json={"title": "x", "start": "2026-11-26T09:00:00", "end": "2026-11-26T10:00:00",
                                        "calendar_id": HOLIDAYS}).status_code == 403

    fake.fail_writes = 400  # Google rejects a new event: keep it on this device and say so
    eid = gc.post("/api/events", json={"title": "Bad", "start": "2026-11-20T09:00:00", "end": "2026-11-20T10:00:00",
                                       "calendar_id": PRIMARY}).json()["id"]
    assert "Bad" in gc.sync()["error"]
    assert gc.get(f"/api/events/{eid}").json()["calendar_id"] == "local"

    fake.fail_writes = 503  # Google is down: keep trying
    eid = gc.post("/api/events", json={"title": "Later", "start": "2026-11-21T09:00:00", "end": "2026-11-21T10:00:00",
                                       "calendar_id": PRIMARY}).json()["id"]
    assert gc.sync()["error"]
    fake.fail_writes = None
    assert gc.sync()["error"] is None
    assert gc.get(f"/api/events/{eid}").json()["google_id"]


def test_move_disable_disconnect(gc, fake):
    fam = urllib.parse.quote(FAMILY, safe="")
    st = gc.put(f"/api/google/calendars/{fam}", json={"enabled": True}).json()
    assert [c["enabled"] for c in st["calendars"] if c["id"] == FAMILY] == [True]
    ev = {"title": "Movie", "start": "2026-11-14T19:00:00", "end": "2026-11-14T21:00:00", "calendar_id": PRIMARY}
    eid = gc.post("/api/events", json=ev).json()["id"]
    gc.sync()
    old_gid = next(iter(fake.events[PRIMARY]))
    gc.put(f"/api/events/{eid}", json={**ev, "calendar_id": FAMILY})
    gc.sync()
    assert fake.events[PRIMARY][old_gid]["status"] == "cancelled"
    assert [e["summary"] for e in fake.events[FAMILY].values()] == ["Movie"]
    assert [(e["title"], e["calendar_id"]) for e in week(gc)] == [("Movie", FAMILY)]

    gc.put(f"/api/google/calendars/{fam}", json={"enabled": False})
    assert week(gc) == []
    gc.post("/api/events", json={**ev, "title": "Mine", "calendar_id": "local"})
    assert gc.post("/api/google/disconnect").status_code == 204
    st = gc.get("/api/google/status").json()
    assert not st["connected"] and st["calendars"] == [] and st["has_client"]  # reconnecting is one tap
    assert [e["title"] for e in week(gc)] == ["Mine"]  # device-only events stay


def test_migrates_old_unique_google_id(tmp_path):
    from skybolt import db as dbmod
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        start TEXT NOT NULL, end TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0,
        description TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
        calendar_id TEXT NOT NULL DEFAULT 'local', google_id TEXT UNIQUE, etag TEXT,
        updated_at TEXT NOT NULL DEFAULT 'x');
        INSERT INTO events (title,start,end) VALUES ('Kept','2026-11-01T09:00:00','2026-11-01T10:00:00');""")
    old.commit(); old.close()
    conn = dbmod.connect(path)
    assert [r["title"] for r in conn.execute("SELECT title FROM events")] == ["Kept"]
    conn.execute("INSERT INTO events (title,start,end,calendar_id,google_id) VALUES ('a','x','x','c1','g')")
    conn.execute("INSERT INTO events (title,start,end,calendar_id,google_id) VALUES ('b','x','x','c2','g')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (title,start,end,calendar_id,google_id) VALUES ('c','x','x','c1','g')")
