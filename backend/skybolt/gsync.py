"""Two-way sync between local events and Google Calendar.

Local edits to events in a Google calendar are marked `pending` ('upsert' or 'delete') and pushed first;
then changes are pulled with Google's incremental sync tokens. Google wins if it refuses a change.
Recurring series stay as one row (its RRULE); changed or cancelled single occurrences are their own rows
(series_gid + original_start) and hide the matching occurrence of the series."""
import logging
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

from . import db as dbmod
from .config import Settings
from .google import Google, GoogleError

log = logging.getLogger("skybolt.gsync")
WRITABLE = ("owner", "writer")
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _q(s: str) -> str:
    return quote(s, safe="")


def to_local(t: dict) -> tuple[datetime, bool]:
    """Google start/end -> (naive local datetime, all_day)."""
    if "date" in t:
        return datetime.fromisoformat(t["date"]), True
    return datetime.fromisoformat(t["dateTime"]).astimezone().replace(tzinfo=None), False


def simple_repeat(lines: list[str], start: datetime) -> str | None:
    """'daily'/'weekly'/'monthly'/'yearly' when the rule is just that, else None (shown as custom)."""
    if len(lines) != 1 or not lines[0].upper().startswith("RRULE:"):
        return None
    parts = dict(p.split("=", 1) for p in lines[0][6:].upper().split(";") if "=" in p)
    freq = parts.pop("FREQ", "").lower()
    if freq not in ("daily", "weekly", "monthly", "yearly"):
        return None
    if parts.get("INTERVAL") == "1":
        parts.pop("INTERVAL")
    parts.pop("WKST", None)
    if freq == "weekly" and parts.get("BYDAY") == DAYS[start.weekday()]:
        parts.pop("BYDAY")
    if freq in ("monthly", "yearly") and parts.get("BYMONTHDAY") == str(start.day):
        parts.pop("BYMONTHDAY")
    if freq == "yearly" and parts.get("BYMONTH") == str(start.month):
        parts.pop("BYMONTH")
    return None if parts else freq


def from_google(it: dict, cal_id: str) -> dict:
    """A (non-cancelled) Google event -> events table columns."""
    start, all_day = to_local(it["start"])
    end, _ = to_local(it["end"])
    if all_day:  # Google's end date is exclusive; ours is the last day at 23:59
        end = max(start, end - timedelta(days=1)).replace(hour=23, minute=59)
    rec = it.get("recurrence") or []
    repeat, rrule = "none", ""
    if rec:
        simple = simple_repeat(rec, start)
        repeat, rrule = (simple, "") if simple else ("custom", "\n".join(rec))
    orig = it.get("originalStartTime")
    return {
        "title": (it.get("summary") or "(No title)")[:500], "start": start.isoformat(), "end": end.isoformat(),
        "all_day": int(all_day), "description": (it.get("description") or "")[:10000],
        "location": (it.get("location") or "")[:1000], "calendar_id": cal_id, "repeat": repeat, "rrule": rrule,
        "series_gid": it.get("recurringEventId"), "original_start": to_local(orig)[0].isoformat() if orig else None,
        "cancelled": 0, "google_id": it["id"], "etag": it.get("etag"),
    }


def to_google(row, member_name: str | None, tz: str) -> dict:
    s, e = datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"])
    if row["all_day"]:
        start, end = {"date": s.date().isoformat()}, {"date": (e.date() + timedelta(days=1)).isoformat()}
    else:
        start, end = {"dateTime": s.astimezone().isoformat()}, {"dateTime": e.astimezone().isoformat()}
        if tz:
            start["timeZone"] = end["timeZone"] = tz
    body = {"summary": row["title"], "description": row["description"], "location": row["location"],
            "start": start, "end": end,
            "extendedProperties": {"private": {"skybolt_member": member_name or ""}}}
    if not row["series_gid"]:  # single occurrences of a series can't carry their own rule
        if row["rrule"]:
            body["recurrence"] = row["rrule"].split("\n")
        else:
            body["recurrence"] = [f"RRULE:FREQ={row['repeat'].upper()}"] if row["repeat"] != "none" else []
    return body


def forget_calendar_events(db, cal_id: str) -> None:
    db.execute("DELETE FROM events WHERE calendar_id=?", (cal_id,))
    db.execute("UPDATE google_calendars SET sync_token=NULL WHERE id=?", (cal_id,))


def _upsert(db, cols: dict, row_id: int | None) -> None:
    if row_id:
        db.execute(f"UPDATE events SET {', '.join(k + '=?' for k in cols)},"
                   " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (*cols.values(), row_id))
    else:
        db.execute(f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   tuple(cols.values()))


class Syncer:
    def __init__(self, settings: Settings, google: Google):
        self.s, self.g = settings, google
        self.lock = threading.Lock()
        self.wake = threading.Event()  # set after a local edit to push it right away
        self.status = {"last_sync": None, "error": None}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- background loop ---------------------------------------------------
    def start(self) -> None:
        if self.s.google_sync_seconds > 0:
            self._thread = threading.Thread(target=self._loop, name="google-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sync()
            self.wake.wait(self.s.google_sync_seconds)
            self.wake.clear()

    # ---- one round ---------------------------------------------------------
    def sync(self) -> None:
        if not self.g.connected():
            return
        with self.lock:
            db = dbmod.connect(self.s.db_path)
            problems: list[str] = []
            try:
                self._calendars(db)
                for (cal_id,) in db.execute("SELECT id FROM google_calendars WHERE enabled=1").fetchall():
                    problems += self._push(db, cal_id)
                    token = db.execute("SELECT sync_token FROM google_calendars WHERE id=?", (cal_id,)).fetchone()[0]
                    self._pull(db, cal_id, token)
                self.status.update(last_sync=datetime.now().isoformat(timespec="seconds"),
                                   error="; ".join(problems) or None)
            except (GoogleError, OSError, ValueError) as e:
                log.warning("Google sync failed: %s", e)
                self.status["error"] = str(e)
            finally:
                db.close()

    def _pages(self, path: str, params: dict):
        page = None
        while True:
            res = self.g.api("GET", path, {**params, **({"pageToken": page} if page else {})})
            yield res
            page = res.get("nextPageToken")
            if not page:
                return

    def _calendars(self, db) -> None:
        seen = set()
        for res in self._pages("/users/me/calendarList", {"maxResults": 250}):
            for it in res.get("items", []):
                if it.get("deleted"):
                    continue
                seen.add(it["id"])
                vals = (it.get("summaryOverride") or it.get("summary") or it["id"], it.get("backgroundColor") or "#4f9cf9",
                        it.get("accessRole", "reader"), int(bool(it.get("primary"))))
                if db.execute("UPDATE google_calendars SET summary=?, color=?, access_role=?, is_primary=? WHERE id=?",
                              (*vals, it["id"])).rowcount == 0:  # new calendars start off, except the main one
                    db.execute("INSERT INTO google_calendars (summary,color,access_role,is_primary,id,enabled)"
                               " VALUES (?,?,?,?,?,?)", (*vals, it["id"], vals[3]))
        for (cal_id,) in db.execute("SELECT id FROM google_calendars").fetchall():
            if cal_id not in seen:  # unsubscribed in Google
                forget_calendar_events(db, cal_id)
                db.execute("DELETE FROM google_calendars WHERE id=?", (cal_id,))
        db.commit()

    def _push(self, db, cal_id: str) -> list[str]:
        problems = []
        members = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM members")}
        path = f"/calendars/{_q(cal_id)}/events"
        for row in db.execute("SELECT * FROM events WHERE calendar_id=? AND pending IS NOT NULL ORDER BY id",
                              (cal_id,)).fetchall():
            try:
                if row["pending"] == "delete":
                    try:
                        self.g.api("DELETE", f"{path}/{_q(row['google_id'])}")
                    except GoogleError as e:
                        if e.status not in (404, 410):  # already gone is fine
                            raise
                    if row["series_gid"]:  # keep hiding that occurrence of the series
                        db.execute("UPDATE events SET pending=NULL, cancelled=1 WHERE id=?", (row["id"],))
                    else:
                        db.execute("DELETE FROM events WHERE id=?", (row["id"],))
                else:
                    body = to_google(row, members.get(row["member_id"]), self.s.timezone)
                    res = (self.g.api("PATCH", f"{path}/{_q(row['google_id'])}", body=body) if row["google_id"]
                           else self.g.api("POST", path, body=body))
                    db.execute("UPDATE events SET google_id=?, etag=?, pending=NULL WHERE id=?",
                               (res["id"], res.get("etag"), row["id"]))
            except GoogleError as e:
                if e.status in (401, 429) or e.status >= 500:
                    raise  # try again next round
                log.warning("Google refused a change to event %s: %s", row["id"], e)
                problems.append(f"Google refused a change to “{row['title']}”: {e}")
                if row["google_id"]:  # re-pull everything so Google's version comes back
                    db.execute("UPDATE events SET pending=NULL WHERE id=?", (row["id"],))
                    db.execute("UPDATE google_calendars SET sync_token=NULL WHERE id=?", (cal_id,))
                else:  # never reached Google: keep it on this device
                    db.execute("UPDATE events SET pending=NULL, calendar_id='local' WHERE id=?", (row["id"],))
            db.commit()
        return problems

    def _pull(self, db, cal_id: str, token: str | None) -> None:
        params = {"showDeleted": "true", "maxResults": 2500}
        if token:
            params["syncToken"] = token
        members = {r["name"].lower(): r["id"] for r in db.execute("SELECT id, name FROM members")}
        seen, res = set(), {}
        try:
            for res in self._pages(f"/calendars/{_q(cal_id)}/events", params):
                for it in res.get("items", []):
                    seen.add(it["id"])
                    self._apply(db, cal_id, it, members)
                db.commit()
        except GoogleError as e:
            if e.status == 410 and token:  # sync token expired: start over
                return self._pull(db, cal_id, None)
            raise
        if not token:  # full sync: drop what Google no longer has
            for r in db.execute("SELECT id, google_id FROM events WHERE calendar_id=? AND google_id IS NOT NULL"
                                " AND pending IS NULL", (cal_id,)).fetchall():
                if r["google_id"] not in seen:
                    db.execute("DELETE FROM events WHERE id=?", (r["id"],))
        db.execute("UPDATE google_calendars SET sync_token=? WHERE id=?", (res.get("nextSyncToken"), cal_id))
        db.commit()

    def _apply(self, db, cal_id: str, it: dict, members: dict) -> None:
        gid = it["id"]
        row = db.execute("SELECT id, pending FROM events WHERE calendar_id=? AND google_id=?", (cal_id, gid)).fetchone()
        if row and row["pending"]:
            return  # a local edit is waiting to be pushed
        if it.get("status") == "cancelled":
            if it.get("recurringEventId") and it.get("originalStartTime"):  # one occurrence removed
                orig = to_local(it["originalStartTime"])[0].isoformat()
                _upsert(db, {"title": "", "start": orig, "end": orig, "calendar_id": cal_id, "cancelled": 1,
                             "series_gid": it["recurringEventId"], "original_start": orig, "google_id": gid,
                             "etag": it.get("etag")}, row and row["id"])
            else:
                db.execute("DELETE FROM events WHERE calendar_id=? AND (google_id=? OR series_gid=?)", (cal_id, gid, gid))
            return
        cols = from_google(it, cal_id)
        private = (it.get("extendedProperties") or {}).get("private") or {}
        if "skybolt_member" in private:
            cols["member_id"] = members.get(private["skybolt_member"].lower())
        _upsert(db, cols, row and row["id"])
