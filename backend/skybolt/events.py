import logging
import sqlite3
from calendar import monthrange
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from . import recur
from .gsync import WRITABLE
from .models import EventIn, EventOut

router = APIRouter(prefix="/api/events", tags=["events"])
log = logging.getLogger("skybolt.events")
MAX_OCCURRENCES = 1000  # safety cap per series per query
VISIBLE = "cancelled=0 AND (pending IS NULL OR pending!='delete')"


def _row(r: sqlite3.Row) -> EventOut:
    d = dict(r)
    d["all_day"] = bool(d["all_day"])
    return EventOut.model_validate(d)


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def _add_months(dt: datetime, n: int) -> datetime:
    """Same day-of-month n months later, clamped (Jan 31 + 1 month -> Feb 28/29)."""
    m = dt.month - 1 + n
    y, m = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, monthrange(y, m)[1]))


def _nth(start: datetime, repeat: str, k: int) -> datetime:
    if repeat == "daily":
        return start + timedelta(days=k)
    if repeat == "weekly":
        return start + timedelta(weeks=k)
    return _add_months(start, k if repeat == "monthly" else 12 * k)


def _expand(ev: EventOut, ws: datetime, we: datetime) -> list[EventOut]:
    """Occurrences of a repeating event that overlap [ws, we). The series id is kept."""
    dur = ev.end - ev.start
    gap = ws - dur - ev.start
    months = (ws.year - ev.start.year) * 12 + ws.month - ev.start.month
    k = max(0, {"daily": gap.days, "weekly": gap.days // 7,
                "monthly": months - 2, "yearly": months // 12 - 1}[ev.repeat])  # start a bit early, then filter
    out = []
    for i in range(MAX_OCCURRENCES):
        s = _nth(ev.start, ev.repeat, k + i)
        if s >= we:
            break
        if s + dur >= ws:
            out.append(ev.model_copy(update={"start": s, "end": s + dur}))
    return out


def _series(r: sqlite3.Row, ws: datetime, we: datetime, skip: set) -> list[EventOut]:
    ev = _row(r)
    dur = ev.end - ev.start
    if r["rrule"]:
        try:
            starts = recur.occurrences(r["rrule"], ev.start, dur, ws, we)
        except (ValueError, KeyError) as e:  # a rule we can't read: show the first occurrence only
            log.warning("cannot expand event %s: %s", r["id"], e)
            starts = [ev.start] if ev.start < we and ev.end >= ws else []
        occ = [ev.model_copy(update={"start": s, "end": s + dur}) for s in starts]
    elif ev.repeat == "custom":
        occ = [ev]
    else:
        occ = _expand(ev, ws, we)
    if r["google_id"]:  # occurrences changed or cancelled in Google are separate rows
        occ = [o for o in occ if (r["calendar_id"], r["google_id"], o.start.isoformat()) not in skip]
    return occ


@router.get("", response_model=list[EventOut])
def list_events(
    request: Request,
    start: datetime | None = Query(None, description="Events ending after this"),
    end: datetime | None = Query(None, description="Events starting before this"),
):
    db = _db(request)
    sql, args = f"SELECT * FROM events WHERE repeat='none' AND {VISIBLE}", []
    if start:
        sql += " AND end >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND start < ?"
        args.append(end.isoformat())
    events = [_row(r) for r in db.execute(sql, args).fetchall()]

    if start and end:  # expand repeating series into the requested window
        ws, we = start.replace(tzinfo=None), end.replace(tzinfo=None)
        skip = {tuple(r) for r in db.execute(
            "SELECT calendar_id, series_gid, original_start FROM events WHERE series_gid IS NOT NULL")}
        for r in db.execute(f"SELECT * FROM events WHERE repeat!='none' AND {VISIBLE} AND start < ?", (we.isoformat(),)):
            events += _series(r, ws, we, skip)
    else:  # no window: return series definitions as-is
        events += [_row(r) for r in db.execute(f"SELECT * FROM events WHERE repeat!='none' AND {VISIBLE}")]
    return sorted(events, key=lambda e: (e.start, e.id))


def _gcal(db: sqlite3.Connection, cal_id: str) -> sqlite3.Row | None:
    """The Google calendar for cal_id, None for 'local'; 400 if unknown or switched off."""
    if cal_id == "local":
        return None
    cal = db.execute("SELECT * FROM google_calendars WHERE id=? AND enabled=1", (cal_id,)).fetchone()
    if cal is None:
        raise HTTPException(400, "unknown calendar")
    return cal


def _writable(db: sqlite3.Connection, cal_id: str) -> sqlite3.Row | None:
    cal = _gcal(db, cal_id)
    if cal is not None and cal["access_role"] not in WRITABLE:
        raise HTTPException(403, "this Google calendar is read-only")
    return cal


def _raw(db: sqlite3.Connection, event_id: int) -> sqlite3.Row:
    r = db.execute(f"SELECT * FROM events WHERE id=? AND {VISIBLE}", (event_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "event not found")
    return r


def _get(db: sqlite3.Connection, event_id: int) -> EventOut:
    return _row(_raw(db, event_id))


def _changed(request: Request, cal) -> None:
    request.app.state.db.commit()
    if cal is not None:
        request.app.state.syncer.wake.set()


@router.post("", response_model=EventOut, status_code=201)
def create_event(request: Request, ev: EventIn):
    db = _db(request)
    if ev.repeat == "custom":
        raise HTTPException(400, "custom repeats can only be set in Google Calendar")
    cal = _writable(db, ev.calendar_id)
    cur = db.execute(
        "INSERT INTO events (title,start,end,all_day,description,location,calendar_id,member_id,repeat,pending)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ev.title, ev.start.isoformat(), ev.end.isoformat(), int(ev.all_day), ev.description, ev.location,
         ev.calendar_id, ev.member_id, ev.repeat, "upsert" if cal is not None else None))
    _changed(request, cal)
    return _get(db, cur.lastrowid)


@router.get("/{event_id}", response_model=EventOut)
def get_event(request: Request, event_id: int):
    """For repeating events this is the series itself (first occurrence), not a single date."""
    return _get(_db(request), event_id)


@router.put("/{event_id}", response_model=EventOut)
def update_event(request: Request, event_id: int, ev: EventIn):
    db = _db(request)
    old = _raw(db, event_id)
    _writable(db, old["calendar_id"])
    cal = _writable(db, ev.calendar_id)
    if ev.repeat == "custom" and not old["rrule"]:
        raise HTTPException(400, "custom repeats can only be set in Google Calendar")
    if old["series_gid"] and (ev.repeat != "none" or ev.calendar_id != old["calendar_id"]):
        raise HTTPException(400, "a single occurrence can't repeat or move to another calendar")
    rrule = old["rrule"] if ev.repeat == "custom" else ""
    google_id, etag = old["google_id"], old["etag"]
    if google_id and ev.calendar_id != old["calendar_id"]:  # moving: delete there, create here
        db.execute("UPDATE events SET google_id=NULL WHERE id=?", (event_id,))
        db.execute("INSERT INTO events (title,start,end,calendar_id,google_id,pending) VALUES (?,?,?,?,?,'delete')",
                   (old["title"], old["start"], old["end"], old["calendar_id"], google_id))
        db.execute("DELETE FROM events WHERE calendar_id=? AND series_gid=?", (old["calendar_id"], google_id))
        google_id = etag = None
    db.execute(
        "UPDATE events SET title=?,start=?,end=?,all_day=?,description=?,location=?,calendar_id=?,member_id=?,"
        "repeat=?,rrule=?,google_id=?,etag=?,pending=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (ev.title, ev.start.isoformat(), ev.end.isoformat(), int(ev.all_day), ev.description, ev.location,
         ev.calendar_id, ev.member_id, ev.repeat, rrule, google_id, etag,
         "upsert" if cal is not None else None, event_id))
    _changed(request, cal or _gcal(db, old["calendar_id"]))
    return _get(db, event_id)


@router.delete("/{event_id}", status_code=204)
def delete_event(request: Request, event_id: int):
    db = _db(request)
    old = _raw(db, event_id)
    cal = _writable(db, old["calendar_id"])
    if old["google_id"]:  # remove from Google on the next sync
        db.execute("UPDATE events SET pending='delete' WHERE id=?", (event_id,))
        if not old["series_gid"]:
            db.execute("DELETE FROM events WHERE calendar_id=? AND series_gid=?", (old["calendar_id"], old["google_id"]))
    else:
        db.execute("DELETE FROM events WHERE id=?", (event_id,))
    _changed(request, cal)
