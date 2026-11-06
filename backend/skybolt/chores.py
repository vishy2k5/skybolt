import sqlite3
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from .models import ChoreDone, ChoreIn, ChoreOut

router = APIRouter(prefix="/api/chores", tags=["chores"])


def _row(r: sqlite3.Row) -> ChoreOut:
    d = dict(r)
    d["done"] = bool(d["done"])
    return ChoreOut.model_validate(d)


def _get(db: sqlite3.Connection, chore_id: int) -> ChoreOut:
    r = db.execute("SELECT * FROM chores WHERE id=?", (chore_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "chore not found")
    return _row(r)


def _check_member(db: sqlite3.Connection, member_id: int | None) -> None:
    if member_id is not None and not db.execute("SELECT 1 FROM members WHERE id=?", (member_id,)).fetchone():
        raise HTTPException(422, "unknown member_id")


@router.get("", response_model=list[ChoreOut])
def list_chores(request: Request):
    """Pending chores plus anything completed today (so the list isn't empty after finishing)."""
    today = date.today().isoformat()
    rows = request.app.state.db.execute(
        "SELECT * FROM chores WHERE done=0 OR done_at >= ? ORDER BY done, due IS NULL, due, id", (today,)
    ).fetchall()
    return [_row(r) for r in rows]


@router.post("", response_model=ChoreOut, status_code=201)
def create_chore(request: Request, c: ChoreIn):
    db = request.app.state.db
    _check_member(db, c.member_id)
    cur = db.execute(
        "INSERT INTO chores (title,member_id,due,repeat) VALUES (?,?,?,?)",
        (c.title.strip(), c.member_id, c.due.isoformat() if c.due else None, c.repeat),
    )
    db.commit()
    return _get(db, cur.lastrowid)


@router.put("/{chore_id}", response_model=ChoreOut)
def update_chore(request: Request, chore_id: int, c: ChoreIn):
    db = request.app.state.db
    _get(db, chore_id)
    _check_member(db, c.member_id)
    db.execute(
        "UPDATE chores SET title=?,member_id=?,due=?,repeat=? WHERE id=?",
        (c.title.strip(), c.member_id, c.due.isoformat() if c.due else None, c.repeat, chore_id),
    )
    db.commit()
    return _get(db, chore_id)


@router.patch("/{chore_id}", response_model=ChoreOut)
def set_done(request: Request, chore_id: int, body: ChoreDone):
    db = request.app.state.db
    chore = _get(db, chore_id)
    if body.done and not chore.done:
        db.execute("UPDATE chores SET done=1, done_at=? WHERE id=?",
                   (datetime.now().isoformat(timespec="seconds"), chore_id))
        _spawn_next(db, chore)
    elif not body.done and chore.done:
        db.execute("UPDATE chores SET done=0, done_at=NULL WHERE id=?", (chore_id,))
    db.commit()
    return _get(db, chore_id)


def _spawn_next(db: sqlite3.Connection, chore: ChoreOut) -> None:
    """Recurring chores: completing one creates the next occurrence (once)."""
    if chore.repeat == "none":
        return
    step = timedelta(days=1 if chore.repeat == "daily" else 7)
    nxt = (chore.due or date.today()) + step
    if nxt <= date.today():  # overdue: restart from today
        nxt = date.today() + step
    dup = db.execute(
        "SELECT 1 FROM chores WHERE done=0 AND title=? AND member_id IS ? AND due=?",
        (chore.title, chore.member_id, nxt.isoformat()),
    ).fetchone()
    if not dup:
        db.execute("INSERT INTO chores (title,member_id,due,repeat) VALUES (?,?,?,?)",
                   (chore.title, chore.member_id, nxt.isoformat(), chore.repeat))


@router.delete("/{chore_id}", status_code=204)
def delete_chore(request: Request, chore_id: int):
    db = request.app.state.db
    _get(db, chore_id)
    db.execute("DELETE FROM chores WHERE id=?", (chore_id,))
    db.commit()
