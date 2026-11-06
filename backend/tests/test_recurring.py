import pytest
from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.main import create_app


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", host="127.0.0.1", port=0, ui_dir=tmp_path / "none")
    with TestClient(create_app(s)) as c:
        yield c


def add(c, title, start, end, repeat="none", all_day=False):
    return c.post("/api/events", json={"title": title, "start": start, "end": end,
                                       "repeat": repeat, "all_day": all_day}).json()


def window(c, a, b):
    return c.get("/api/events", params={"start": a, "end": b}).json()


def test_daily_and_weekly(client):
    add(client, "Pills", "2026-11-01T08:00:00", "2026-11-01T08:15:00", "daily")
    add(client, "Trash", "2026-11-02T07:00:00", "2026-11-02T07:30:00", "weekly")
    evs = window(client, "2026-11-08T00:00:00", "2026-11-15T00:00:00")
    assert len([e for e in evs if e["title"] == "Pills"]) == 7
    assert [e["start"][:10] for e in evs if e["title"] == "Trash"] == ["2026-11-09"]


def test_monthly_clamps_to_month_end(client):
    add(client, "Rent", "2026-01-31T09:00:00", "2026-01-31T10:00:00", "monthly")
    feb = window(client, "2026-02-01T00:00:00", "2026-03-01T00:00:00")
    assert [e["start"][:10] for e in feb] == ["2026-02-28"]
    mar = window(client, "2026-03-01T00:00:00", "2026-04-01T00:00:00")
    assert [e["start"][:10] for e in mar] == ["2026-03-31"]


def test_yearly_birthday_all_day(client):
    add(client, "Mia's birthday", "2020-11-10T00:00:00", "2020-11-10T23:59:00", "yearly", all_day=True)
    evs = window(client, "2026-11-01T00:00:00", "2026-12-01T00:00:00")
    assert len(evs) == 1 and evs[0]["start"].startswith("2026-11-10") and evs[0]["all_day"]
    assert window(client, "2026-12-01T00:00:00", "2027-01-01T00:00:00") == []


def test_yearly_leap_day(client):
    add(client, "Leap", "2024-02-29T00:00:00", "2024-02-29T23:59:00", "yearly", all_day=True)
    assert window(client, "2026-02-01T00:00:00", "2026-03-01T00:00:00")[0]["start"].startswith("2026-02-28")
    assert window(client, "2028-02-01T00:00:00", "2028-03-01T00:00:00")[0]["start"].startswith("2028-02-29")


def test_not_before_series_start(client):
    add(client, "Pills", "2026-11-10T08:00:00", "2026-11-10T08:15:00", "daily")
    assert window(client, "2026-11-01T00:00:00", "2026-11-10T00:00:00") == []


def test_series_keeps_id_and_get_returns_master(client):
    e = add(client, "Pills", "2026-11-01T08:00:00", "2026-11-01T08:15:00", "daily")
    assert {x["id"] for x in window(client, "2026-11-05T00:00:00", "2026-11-08T00:00:00")} == {e["id"]}
    assert client.get(f"/api/events/{e['id']}").json()["start"].startswith("2026-11-01")


def test_no_window_returns_master_and_edit_delete(client):
    e = add(client, "Pills", "2026-11-01T08:00:00", "2026-11-01T08:15:00", "daily")
    assert len(client.get("/api/events").json()) == 1
    r = client.put(f"/api/events/{e['id']}", json={**e, "repeat": "weekly"}).json()
    assert r["repeat"] == "weekly"
    client.delete(f"/api/events/{e['id']}")
    assert window(client, "2026-11-01T00:00:00", "2026-12-01T00:00:00") == []


def test_invalid_repeat(client):
    assert client.post("/api/events", json={"title": "x", "start": "2026-11-01T08:00:00",
                                            "end": "2026-11-01T09:00:00", "repeat": "hourly"}).status_code == 422
