import sqlite3
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from .models import EventIn, EventOut

router = APIRouter(prefix="/api/events", tags=["events"])


def _row(r: sqlite3.Row) -> EventOut:
    d = dict(r)
    d["all_day"] = bool(d["all_day"])
    return EventOut.model_validate(d)


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.get("", response_model=list[EventOut])
def list_events(
    request: Request,
    start: datetime | None = Query(None, description="Events ending after this"),
    end: datetime | None = Query(None, description="Events starting before this"),
):
    sql, args = "SELECT * FROM events WHERE 1=1", []
    if start:
        sql += " AND end >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND start < ?"
        args.append(end.isoformat())
    rows = _db(request).execute(sql + " ORDER BY start", args).fetchall()
    return [_row(r) for r in rows]


@router.post("", response_model=EventOut, status_code=201)
def create_event(request: Request, ev: EventIn):
    db = _db(request)
    cur = db.execute(
        "INSERT INTO events (title,start,end,all_day,description,location,calendar_id,member_id)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (ev.title, ev.start.isoformat(), ev.end.isoformat(), int(ev.all_day),
         ev.description, ev.location, ev.calendar_id, ev.member_id),
    )
    db.commit()
    return _get(db, cur.lastrowid)


def _get(db: sqlite3.Connection, event_id: int) -> EventOut:
    r = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "event not found")
    return _row(r)


@router.get("/{event_id}", response_model=EventOut)
def get_event(request: Request, event_id: int):
    return _get(_db(request), event_id)


@router.put("/{event_id}", response_model=EventOut)
def update_event(request: Request, event_id: int, ev: EventIn):
    db = _db(request)
    _get(db, event_id)
    db.execute(
        "UPDATE events SET title=?,start=?,end=?,all_day=?,description=?,location=?,"
        "calendar_id=?,member_id=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (ev.title, ev.start.isoformat(), ev.end.isoformat(), int(ev.all_day),
         ev.description, ev.location, ev.calendar_id, ev.member_id, event_id),
    )
    db.commit()
    return _get(db, event_id)


@router.delete("/{event_id}", status_code=204)
def delete_event(request: Request, event_id: int):
    db = _db(request)
    _get(db, event_id)
    db.execute("DELETE FROM events WHERE id=?", (event_id,))
    db.commit()
