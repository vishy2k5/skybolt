import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .models import ShoppingDone, ShoppingIn, ShoppingOut

router = APIRouter(prefix="/api/shopping", tags=["shopping"])

MAX_ITEMS = 500  # per list, checked ones included; a family list never gets near this
HISTORY_MAX = 300  # remembered names per list (the least used and oldest go first)
SUGGESTIONS = 30  # names offered per list


def _db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def _out(r: sqlite3.Row) -> ShoppingOut:
    return ShoppingOut(id=r["id"], name=r["name"], note=r["note"], list=r["list"],
                       done=bool(r["done"]), done_at=r["done_at"])


def _get(db: sqlite3.Connection, item_id: int) -> sqlite3.Row:
    r = db.execute("SELECT * FROM shopping_items WHERE id=?", (item_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "item not found")
    return r


def _same_name(db: sqlite3.Connection, lst: str, name: str, skip: int | None = None) -> sqlite3.Row | None:
    key = name.casefold()
    for r in db.execute("SELECT * FROM shopping_items WHERE list=? AND id IS NOT ?", (lst, skip)):
        if r["name"].casefold() == key:
            return r
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _remember(db: sqlite3.Connection, lst: str, name: str, uses: int = 1) -> None:
    db.execute("INSERT INTO shopping_history (list,key,name,uses,last_used) VALUES (?,?,?,?,?) "
               "ON CONFLICT(list,key) DO UPDATE SET name=excluded.name, uses=uses+excluded.uses, last_used=excluded.last_used",
               (lst, name.casefold(), name, uses, _now()))
    db.execute("DELETE FROM shopping_history WHERE list=? AND key NOT IN "
               "(SELECT key FROM shopping_history WHERE list=? ORDER BY uses DESC, last_used DESC LIMIT ?)",
               (lst, lst, HISTORY_MAX))


def _forget(db: sqlite3.Connection, lst: str, name: str) -> int:
    """Drop a name from the suggestions; returns how often it had been used (0 if it was not there)."""
    r = db.execute("SELECT uses FROM shopping_history WHERE list=? AND key=?", (lst, name.casefold())).fetchone()
    db.execute("DELETE FROM shopping_history WHERE list=? AND key=?", (lst, name.casefold()))
    return r["uses"] if r else 0


@router.get("", response_model=list[ShoppingOut])
def list_items(request: Request, list: str | None = Query(default=None, pattern="^(grocery|order)$")):
    """Still-to-get items first (oldest first), then checked ones (most recently checked first)."""
    sql, args = "SELECT * FROM shopping_items", ()
    if list:
        sql, args = sql + " WHERE list=?", (list,)
    rows = _db(request).execute(sql + " ORDER BY done, CASE WHEN done=0 THEN id END, done_at DESC, id", args)
    return [_out(r) for r in rows]


@router.get("/suggestions", response_model=dict[str, list[str]])
def suggestions(request: Request):
    """Names bought before and not on the list right now, most used first, for each list."""
    db, out = _db(request), {}
    for lst in ("grocery", "order"):
        here = {r["name"].casefold() for r in db.execute("SELECT name FROM shopping_items WHERE list=?", (lst,))}
        rows = db.execute("SELECT name, key FROM shopping_history WHERE list=? ORDER BY uses DESC, last_used DESC, key", (lst,))
        out[lst] = [r["name"] for r in rows if r["key"] not in here][:SUGGESTIONS]
    return out


@router.post("", response_model=ShoppingOut, status_code=201)
def add_item(request: Request, item: ShoppingIn, response: Response):
    """Adding something already on the list does not duplicate it: an open one stays as is, a checked one comes back."""
    db = _db(request)
    same = _same_name(db, item.list, item.name)
    if same is not None:
        response.status_code = 200
        if same["done"]:
            _remember(db, item.list, same["name"])  # bought again
        if same["done"] or (item.note and item.note != same["note"]):
            db.execute("UPDATE shopping_items SET done=0, done_at=NULL, note=? WHERE id=?",
                       (item.note or same["note"], same["id"]))
            db.commit()
        return _out(_get(db, same["id"]))
    if db.execute("SELECT COUNT(*) FROM shopping_items WHERE list=?", (item.list,)).fetchone()[0] >= MAX_ITEMS:
        raise HTTPException(422, "this list is full: clear some checked items first")
    cur = db.execute("INSERT INTO shopping_items (name,note,list) VALUES (?,?,?)", (item.name, item.note, item.list))
    _remember(db, item.list, item.name)
    db.commit()
    return _out(_get(db, cur.lastrowid))


@router.delete("/done")
def clear_done(request: Request, list: str | None = Query(default=None, pattern="^(grocery|order)$")):
    """Remove every checked item (from one list, or both). The removed items come back in the answer, so a client can undo."""
    db = _db(request)
    where, args = "done=1" + (" AND list=?" if list else ""), (list,) if list else ()
    rows = db.execute(f"SELECT * FROM shopping_items WHERE {where} ORDER BY id", args).fetchall()
    db.execute(f"DELETE FROM shopping_items WHERE {where}", args)
    db.commit()
    return {"deleted": len(rows), "items": [_out(r) for r in rows]}


@router.put("/{item_id}", response_model=ShoppingOut)
def update_item(request: Request, item_id: int, item: ShoppingIn):
    db = _db(request)
    old = _get(db, item_id)
    if _same_name(db, item.list, item.name, skip=item_id) is not None:
        raise HTTPException(409, "that is already on the list")
    if (old["list"], old["name"]) != (item.list, item.name):  # renamed (a fixed typo) or moved: the suggestion follows it
        _remember(db, item.list, item.name, uses=_forget(db, old["list"], old["name"]) or 1)
    db.execute("UPDATE shopping_items SET name=?, note=?, list=? WHERE id=?", (item.name, item.note, item.list, item_id))
    db.commit()
    return _out(_get(db, item_id))


@router.patch("/{item_id}", response_model=ShoppingOut)
def set_done(request: Request, item_id: int, body: ShoppingDone):
    db = _db(request)
    _get(db, item_id)
    when = datetime.now(timezone.utc).isoformat(timespec="seconds") if body.done else None
    db.execute("UPDATE shopping_items SET done=?, done_at=? WHERE id=?", (int(body.done), when, item_id))
    db.commit()
    return _out(_get(db, item_id))


@router.delete("/{item_id}", status_code=204)
def delete_item(request: Request, item_id: int):
    db = _db(request)
    r = _get(db, item_id)
    _forget(db, r["list"], r["name"])  # deleting (as opposed to clearing) means it was a mistake: stop suggesting it
    db.execute("DELETE FROM shopping_items WHERE id=?", (item_id,))
    db.commit()
