import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.db import connect
from skybolt.main import create_app

TODAY = date.today()
D = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", host="127.0.0.1", port=0, ui_dir=tmp_path / "none")
    with TestClient(create_app(s)) as c:
        yield c


def rng(client, a=0, b=7):
    return client.get("/api/chores", params={"start": D(a), "end": D(b)}).json()


def test_timed_and_all_day(client):
    m = client.post("/api/members", json={"name": "Mia"}).json()
    t = client.post("/api/chores", json={"title": "Walk dog", "member_id": m["id"], "due": D(1), "start_time": "07:30"}).json()
    assert t["start_time"] == "07:30" and t["end_time"] == "08:00"  # default 30 minutes
    a = client.post("/api/chores", json={"title": "Laundry", "due": D(1)}).json()
    assert a["start_time"] is None and a["member_id"] is None  # all-day, for everyone
    day = rng(client, 1, 2)
    assert [c["title"] for c in day] == ["Laundry", "Walk dog"]  # all-day first
    assert rng(client, 2, 3) == []


def test_end_of_day_default_is_capped(client):
    c = client.post("/api/chores", json={"title": "Late", "due": D(0), "start_time": "23:50"}).json()
    assert c["end_time"] == "23:59"


def test_repeating_expands_per_day_with_own_done_state(client):
    c = client.post("/api/chores", json={"title": "Dishes", "due": D(0), "repeat": "daily"}).json()
    week = rng(client, 0, 7)
    assert [x["day"] for x in week] == [D(i) for i in range(7)]
    client.patch(f"/api/chores/{c['id']}", json={"done": True, "day": D(2)})
    week = rng(client, 0, 7)
    assert [x["done"] for x in week] == [False, False, True, False, False, False, False]
    # does not appear before its first day
    assert rng(client, -3, 0) == []
    client.patch(f"/api/chores/{c['id']}", json={"done": False, "day": D(2)})
    assert not any(x["done"] for x in rng(client))


def test_weekly(client):
    client.post("/api/chores", json={"title": "Trash", "due": D(1), "repeat": "weekly"})
    assert [x["day"] for x in rng(client, 0, 15)] == [D(1), D(8)]  # D(15) is outside [0, 15)
    assert [x["day"] for x in rng(client, 3, 12)] == [D(8)]  # window starting mid-cycle


def test_repeating_needs_a_valid_day(client):
    c = client.post("/api/chores", json={"title": "Trash", "due": D(1), "repeat": "weekly"}).json()
    assert client.patch(f"/api/chores/{c['id']}", json={"done": True}).status_code == 422
    assert client.patch(f"/api/chores/{c['id']}", json={"done": True, "day": D(2)}).status_code == 422
    assert client.patch(f"/api/chores/{c['id']}", json={"done": True, "day": D(8)}).json()["done"] is True


def test_one_off_done_and_open_list(client):
    late = client.post("/api/chores", json={"title": "Overdue", "due": D(-2)}).json()
    anytime = client.post("/api/chores", json={"title": "Water plants"}).json()
    client.post("/api/chores", json={"title": "Future", "due": D(3)})
    assert [c["title"] for c in client.get("/api/chores/open").json()] == ["Overdue", "Water plants"]
    r = client.patch(f"/api/chores/{anytime['id']}", json={"done": True}).json()
    assert r["done"] and r["done_at"]
    assert [c["title"] for c in client.get("/api/chores/open").json()] == ["Overdue"]
    client.patch(f"/api/chores/{late['id']}", json={"done": True})
    assert client.get("/api/chores/open").json() == []
    assert rng(client, -2, -1)[0]["done"] is True


def test_moving_a_one_off_clears_its_tick(client):
    c = client.post("/api/chores", json={"title": "x", "due": D(0)}).json()
    client.patch(f"/api/chores/{c['id']}", json={"done": True})
    client.put(f"/api/chores/{c['id']}", json={"title": "x", "due": D(1)})
    assert rng(client, 1, 2)[0]["done"] is False


def test_edit_and_delete(client):
    c = client.post("/api/chores", json={"title": "x", "due": D(0), "repeat": "daily"}).json()
    client.patch(f"/api/chores/{c['id']}", json={"done": True, "day": D(0)})
    r = client.put(f"/api/chores/{c['id']}", json={"title": "y", "due": D(0), "start_time": "09:00", "end_time": "10:00", "repeat": "daily"}).json()
    assert r["title"] == "y" and r["end_time"] == "10:00"
    assert client.delete(f"/api/chores/{c['id']}").status_code == 204
    assert rng(client) == [] and client.delete(f"/api/chores/{c['id']}").status_code == 404


@pytest.mark.parametrize("body", [
    {"title": "x", "member_id": 999},
    {"title": "x", "repeat": "yearly"},
    {"title": "x", "repeat": "daily"},                                   # repeating needs a date
    {"title": "x", "start_time": "09:00"},                               # timed needs a date
    {"title": "x", "due": D(0), "end_time": "10:00"},                    # end without start
    {"title": "x", "due": D(0), "start_time": "10:00", "end_time": "09:00"},
    {"title": "x", "due": D(0), "start_time": "25:00"},
    {"title": ""},
])
def test_validation(client, body):
    assert client.post("/api/chores", json=body).status_code == 422


def test_range_limits(client):
    assert client.get("/api/chores", params={"start": D(5), "end": D(5)}).status_code == 422
    assert client.get("/api/chores", params={"start": D(0), "end": D(500)}).status_code == 422


def test_deleting_member_makes_chore_for_everyone(client):
    m = client.post("/api/members", json={"name": "Mia"}).json()
    client.post("/api/chores", json={"title": "x", "member_id": m["id"], "due": D(0)})
    client.delete(f"/api/members/{m['id']}")
    assert rng(client, 0, 1)[0]["member_id"] is None


def test_migrates_old_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE members (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL);
        CREATE TABLE chores (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            member_id INTEGER REFERENCES members(id) ON DELETE SET NULL, due TEXT,
            repeat TEXT NOT NULL DEFAULT 'none', done INTEGER NOT NULL DEFAULT 0, done_at TEXT);
    """)
    old.executemany("INSERT INTO chores (title,due,repeat,done,done_at) VALUES (?,?,?,?,?)", [
        ("Dishes", D(-1), "daily", 1, D(-1) + "T20:00:00"),   # finished occurrence of a series
        ("Dishes", D(0), "daily", 0, None),                   # ...its next occurrence: carries the series
        ("Plants", None, "none", 0, None),
        ("Trash", None, "weekly", 0, None),                   # repeating but undated: gets today
    ])
    old.commit(); old.close()
    s = Settings(db_path=path, host="127.0.0.1", port=0, ui_dir=tmp_path / "none")
    with TestClient(create_app(s)) as c:
        got = rng(c, -1, 1)
        dishes = [x for x in got if x["title"] == "Dishes"]
        assert [(x["day"], x["done"]) for x in dishes] == [(D(-1), True), (D(0), False)]  # no duplicates
        assert [x["title"] for x in c.get("/api/chores/open").json()] == ["Plants"]
        assert any(x["title"] == "Trash" and x["day"] == D(0) for x in got)
    connect(path).close()  # second open must not migrate again
