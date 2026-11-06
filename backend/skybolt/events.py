import sqlite3
from calendar import monthrange
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from .models import EventIn, EventOut

router = APIRouter(prefix="/api/events", tags=["events"])
MAX_OCCURRENCES = 1000  # safety cap per series per query


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


@router.get("", response_model=list[EventOut])
def list_events(
    request: Request,
    start: datetime | None = Query(None, description="Events ending after this"),
    end: datetime | None = Query(None, description="Events starting before this"),
):
    db = _db(request)
    sql, args = "SELECT * FROM events WHERE repeat='none'", []
    if start:
        sql += " AND end >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND start < ?"
        args.append(end.isoformat())
    events = [_row(r) for r in db.execute(sql, args).fetchall()]

    if start and end:  # expand repeating series into the requested window
        ws, we = start.replace(tzinfo=None), end.replace(tzinfo=None)
        for r in db.execute("SELECT * FROM events WHERE repeat!='none' AND start < ?", (we.isoformat(),)):
            events += _expand(_row(r), ws, we)
    else:  # no window: return series definitions as-is
        events += [_row(r) for r in db.execute("SELECT * FROM events WHERE repeat!='none'")]
    return sorted(events, key=lambda e: (e.start, e.id))


def _values(ev: EventIn) -> tuple:
    return (ev.title, ev.start.isoformat(), ev.end.isoformat(), int(ev.all_day), ev.description,
            ev.location, ev.calendar_id, ev.member_id, ev.repeat)


@router.post("", response_model=EventOut, status_code=201)
def create_event(request: Request, ev: EventIn):
    db = _db(request)
    cur = db.execute(
        "INSERT INTO events (title,start,end,all_day,description,location,calendar_id,member_id,repeat)"
        " VALUES (?,?,?,?,?,?,?,?,?)", _values(ev))
    db.commit()
    return _get(db, cur.lastrowid)


def _get(db: sqlite3.Connection, event_id: int) -> EventOut:
    r = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "event not found")
    return _row(r)


@router.get("/{event_id}", response_model=EventOut)
def get_event(request: Request, event_id: int):
    """For repeating events this is the series itself (first occurrence), not a single date."""
    return _get(_db(request), event_id)


@router.put("/{event_id}", response_model=EventOut)
def update_event(request: Request, event_id: int, ev: EventIn):
    db = _db(request)
    _get(db, event_id)
    db.execute(
        "UPDATE events SET title=?,start=?,end=?,all_day=?,description=?,location=?,calendar_id=?,"
        "member_id=?,repeat=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (*_values(ev), event_id))
    db.commit()
    return _get(db, event_id)


@router.delete("/{event_id}", status_code=204)
def delete_event(request: Request, event_id: int):
    db = _db(request)
    _get(db, event_id)
    db.execute("DELETE FROM events WHERE id=?", (event_id,))
    db.commit()
