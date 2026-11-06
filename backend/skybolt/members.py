import sqlite3

from fastapi import APIRouter, HTTPException, Request

from .models import MemberIn, MemberOut

router = APIRouter(prefix="/api/members", tags=["members"])

PALETTE = ["#4f9cf9", "#f2994a", "#6fcf97", "#bb6bd9", "#eb5757", "#f2c94c", "#56ccf2", "#9b9b9b"]


@router.get("", response_model=list[MemberOut])
def list_members(request: Request):
    rows = request.app.state.db.execute("SELECT * FROM members ORDER BY id").fetchall()
    return [MemberOut(**dict(r)) for r in rows]


@router.post("", response_model=MemberOut, status_code=201)
def create_member(request: Request, m: MemberIn):
    db = request.app.state.db
    color = m.color
    if not color:
        n = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        color = PALETTE[n % len(PALETTE)]
    try:
        cur = db.execute("INSERT INTO members (name,color) VALUES (?,?)", (m.name.strip(), color))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "a person with that name already exists")
    db.commit()
    return MemberOut(id=cur.lastrowid, name=m.name.strip(), color=color)


@router.put("/{member_id}", response_model=MemberOut)
def update_member(request: Request, member_id: int, m: MemberIn):
    db = request.app.state.db
    row = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "person not found")
    color = m.color or row["color"]
    try:
        db.execute("UPDATE members SET name=?, color=? WHERE id=?", (m.name.strip(), color, member_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "a person with that name already exists")
    db.commit()
    return MemberOut(id=member_id, name=m.name.strip(), color=color)


@router.delete("/{member_id}", status_code=204)
def delete_member(request: Request, member_id: int):
    db = request.app.state.db
    if db.execute("DELETE FROM members WHERE id=?", (member_id,)).rowcount == 0:
        raise HTTPException(404, "person not found")
    db.commit()
