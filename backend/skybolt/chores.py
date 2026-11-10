import sqlite3
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from .models import ChoreDone, ChoreIn, ChoreOut

router = APIRouter(prefix="/api/chores", tags=["chores"])

MAX_RANGE_DAYS = 400
DEFAULT_MINUTES = 30


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def _occurrence(r: sqlite3.Row, day: date | None, done_at: str | None) -> ChoreOut:
    return ChoreOut.model_validate({
        "id": r["id"], "title": r["title"], "member_id": r["member_id"],
        "due": r["due"], "start_time": r["start_time"], "end_time": r["end_time"], "repeat": r["repeat"],
        "day": day, "done": done_at is not None, "done_at": done_at or None})


def _get_row(db: sqlite3.Connection, chore_id: int) -> sqlite3.Row:
    r = db.execute("SELECT * FROM chores WHERE id=?", (chore_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "chore not found")
    return r


def _check_member(db: sqlite3.Connection, member_id: int | None) -> None:
    if member_id is not None and not db.execute("SELECT 1 FROM members WHERE id=?", (member_id,)).fetchone():
        raise HTTPException(422, "unknown member_id")


def _days(r: sqlite3.Row, ws: date, we: date) -> list[date]:
    """The days in [ws, we) this chore falls on."""
    if not r["due"]:
        return []
    due = date.fromisoformat(r["due"])
    if r["repeat"] == "none":
        return [due] if ws <= due < we else []
    step = 1 if r["repeat"] == "daily" else 7
    first = max(ws, due)
    d = due + timedelta(days=-(-(first - due).days // step) * step)  # first occurrence on or after `first`
    out = []
    while d < we:
        out.append(d)
        d += timedelta(days=step)
    return out


def _end_time(c: ChoreIn) -> str | None:
    """A timed chore with no end time gets a default length, so it always has a block on the grid."""
    if not c.start_time or c.end_time:
        return c.end_time
    h, m = map(int, c.start_time.split(":"))
    end = min(h * 60 + m + DEFAULT_MINUTES, 23 * 60 + 59)
    return f"{end // 60:02d}:{end % 60:02d}"


def _values(c: ChoreIn) -> tuple:
    return (c.title.strip(), c.member_id, c.due.isoformat() if c.due else None,
            c.start_time, _end_time(c), c.repeat)


@router.get("", response_model=list[ChoreOut])
def list_chores(request: Request, start: date, end: date):
    """Every chore occurrence on the days in [start, end), repeating ones expanded, each with its done state."""
    if end <= start or (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(422, "start must be before end, and the range at most a year")
    db = _db(request)
    done = {(r["chore_id"], r["day"]): r["done_at"] for r in db.execute(
        "SELECT chore_id, day, done_at FROM chore_done WHERE day >= ? AND day < ?", (start.isoformat(), end.isoformat()))}
    out = []
    for r in db.execute("SELECT * FROM chores WHERE due IS NOT NULL ORDER BY id"):
        out += [_occurrence(r, d, done.get((r["id"], d.isoformat()))) for d in _days(r, start, end)]
    out.sort(key=lambda c: (c.day, c.start_time or "", c.id))
    return out


@router.get("/open", response_model=list[ChoreOut])
def open_chores(request: Request):
    """One-off chores still to do that have no date or are overdue (they would otherwise have no place on the grid)."""
    today = date.today().isoformat()
    rows = _db(request).execute(
        "SELECT c.* FROM chores c WHERE c.repeat='none' AND (c.due IS NULL OR c.due < ?) "
        "AND NOT EXISTS (SELECT 1 FROM chore_done d WHERE d.chore_id=c.id) ORDER BY c.due IS NULL, c.due, c.id",
        (today,)).fetchall()
    return [_occurrence(r, date.fromisoformat(r["due"]) if r["due"] else None, None) for r in rows]


@router.post("", response_model=ChoreOut, status_code=201)
def create_chore(request: Request, c: ChoreIn):
    db = _db(request)
    _check_member(db, c.member_id)
    cur = db.execute("INSERT INTO chores (title,member_id,due,start_time,end_time,repeat) VALUES (?,?,?,?,?,?)", _values(c))
    db.commit()
    return _occurrence(_get_row(db, cur.lastrowid), c.due, None)


@router.put("/{chore_id}", response_model=ChoreOut)
def update_chore(request: Request, chore_id: int, c: ChoreIn):
    db = _db(request)
    _get_row(db, chore_id)
    _check_member(db, c.member_id)
    db.execute("UPDATE chores SET title=?,member_id=?,due=?,start_time=?,end_time=?,repeat=? WHERE id=?",
               (*_values(c), chore_id))
    if c.repeat == "none":  # moved to another day: the old tick no longer applies
        db.execute("DELETE FROM chore_done WHERE chore_id=? AND day!=?", (chore_id, c.due.isoformat() if c.due else ""))
    db.commit()
    return _occurrence(_get_row(db, chore_id), c.due, None)


@router.patch("/{chore_id}", response_model=ChoreOut)
def set_done(request: Request, chore_id: int, body: ChoreDone):
    db = _db(request)
    r = _get_row(db, chore_id)
    if r["repeat"] == "none":
        day = date.fromisoformat(r["due"]) if r["due"] else None
    else:
        day = body.day
        if day is None or not _days(r, day, day + timedelta(days=1)):
            raise HTTPException(422, "day must be a day this chore occurs on")
    key = day.isoformat() if day else ""
    if body.done:
        db.execute("INSERT OR IGNORE INTO chore_done (chore_id, day, done_at) VALUES (?,?,?)",
                   (chore_id, key, datetime.now().isoformat(timespec="seconds")))
    else:
        db.execute("DELETE FROM chore_done WHERE chore_id=? AND day=?", (chore_id, key))
    db.commit()
    got = db.execute("SELECT done_at FROM chore_done WHERE chore_id=? AND day=?", (chore_id, key)).fetchone()
    return _occurrence(r, day, got["done_at"] if got else None)


@router.delete("/{chore_id}", status_code=204)
def delete_chore(request: Request, chore_id: int):
    db = _db(request)
    _get_row(db, chore_id)
    db.execute("DELETE FROM chores WHERE id=?", (chore_id,))
    db.commit()
