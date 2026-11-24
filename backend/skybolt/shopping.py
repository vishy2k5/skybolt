import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .models import ShoppingDone, ShoppingIn, ShoppingOut

router = APIRouter(prefix="/api/shopping", tags=["shopping"])

MAX_ITEMS = 500  # per list, checked ones included; a family list never gets near this


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


@router.get("", response_model=list[ShoppingOut])
def list_items(request: Request, list: str | None = Query(default=None, pattern="^(grocery|order)$")):
    """Still-to-get items first (oldest first), then checked ones (most recently checked first)."""
    sql, args = "SELECT * FROM shopping_items", ()
    if list:
        sql, args = sql + " WHERE list=?", (list,)
    rows = _db(request).execute(sql + " ORDER BY done, CASE WHEN done=0 THEN id END, done_at DESC, id", args)
    return [_out(r) for r in rows]


@router.post("", response_model=ShoppingOut, status_code=201)
def add_item(request: Request, item: ShoppingIn, response: Response):
    """Adding something already on the list does not duplicate it: an open one stays as is, a checked one comes back."""
    db = _db(request)
    same = _same_name(db, item.list, item.name)
    if same is not None:
        response.status_code = 200
        if same["done"] or (item.note and item.note != same["note"]):
            db.execute("UPDATE shopping_items SET done=0, done_at=NULL, note=? WHERE id=?",
                       (item.note or same["note"], same["id"]))
            db.commit()
        return _out(_get(db, same["id"]))
    if db.execute("SELECT COUNT(*) FROM shopping_items WHERE list=?", (item.list,)).fetchone()[0] >= MAX_ITEMS:
        raise HTTPException(422, "this list is full: clear some checked items first")
    cur = db.execute("INSERT INTO shopping_items (name,note,list) VALUES (?,?,?)", (item.name, item.note, item.list))
    db.commit()
    return _out(_get(db, cur.lastrowid))


@router.delete("/done")
def clear_done(request: Request, list: str | None = Query(default=None, pattern="^(grocery|order)$")):
    """Remove every checked item (from one list, or both)."""
    db = _db(request)
    cur = db.execute("DELETE FROM shopping_items WHERE done=1" + (" AND list=?" if list else ""), (list,) if list else ())
    db.commit()
    return {"deleted": cur.rowcount}


@router.put("/{item_id}", response_model=ShoppingOut)
def update_item(request: Request, item_id: int, item: ShoppingIn):
    db = _db(request)
    _get(db, item_id)
    if _same_name(db, item.list, item.name, skip=item_id) is not None:
        raise HTTPException(409, "that is already on the list")
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
    _get(db, item_id)
    db.execute("DELETE FROM shopping_items WHERE id=?", (item_id,))
    db.commit()
