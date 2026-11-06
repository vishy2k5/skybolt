from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.main import create_app

RAW = {
    "current": {"time": "2026-11-05T09:30", "temperature_2m": 54.4, "apparent_temperature": 51.0,
                "relative_humidity_2m": 60, "weather_code": 2, "wind_speed_10m": 7.2, "is_day": 1},
    "hourly": {"time": [f"2026-11-05T{h:02d}:00" for h in range(24)],
               "temperature_2m": [50.0] * 24, "weather_code": [1] * 24, "precipitation_probability": [10] * 24},
    "daily": {"time": [f"2026-11-{5 + i:02d}" for i in range(7)], "weather_code": [3] * 7,
              "temperature_2m_max": [60.2] * 7, "temperature_2m_min": [41.0] * 7,
              "precipitation_probability_max": [20] * 7,
              "sunrise": ["2026-11-05T06:30"] * 7, "sunset": ["2026-11-05T16:50"] * 7},
}


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", host="127.0.0.1", port=0, ui_dir=tmp_path / "none")
    app = create_app(s)
    with TestClient(app) as c:
        c.calls = 0

        def fake(_, units):
            c.calls += 1
            if c.fail:
                raise OSError("offline")
            return RAW
        c.fail = False
        app.state.weather_fetch = fake
        yield c


def test_members(client):
    a = client.post("/api/members", json={"name": "Mia"}).json()
    b = client.post("/api/members", json={"name": "Sam"}).json()
    assert a["color"] != b["color"]
    assert client.post("/api/members", json={"name": "Mia"}).status_code == 409
    assert len(client.get("/api/members").json()) == 2


def test_chore_flow_and_repeat(client):
    m = client.post("/api/members", json={"name": "Mia"}).json()
    today = date.today()
    c = client.post("/api/chores", json={"title": "Dishes", "member_id": m["id"],
                                         "due": today.isoformat(), "repeat": "daily"}).json()
    r = client.patch(f"/api/chores/{c['id']}", json={"done": True}).json()
    assert r["done"] and r["done_at"]
    chores = client.get("/api/chores").json()
    pending = [x for x in chores if not x["done"]]
    assert len(pending) == 1 and pending[0]["due"] == (today + timedelta(days=1)).isoformat()
    # re-completing / undoing doesn't duplicate
    client.patch(f"/api/chores/{c['id']}", json={"done": False})
    client.patch(f"/api/chores/{c['id']}", json={"done": True})
    assert len([x for x in client.get("/api/chores").json() if not x["done"]]) == 1


def test_chore_validation(client):
    assert client.post("/api/chores", json={"title": "x", "member_id": 999}).status_code == 422
    assert client.post("/api/chores", json={"title": "x", "repeat": "yearly"}).status_code == 422


def test_deleting_member_unassigns(client):
    m = client.post("/api/members", json={"name": "Mia"}).json()
    c = client.post("/api/chores", json={"title": "x", "member_id": m["id"]}).json()
    client.delete(f"/api/members/{m['id']}")
    assert client.get("/api/chores").json()[0]["member_id"] is None and c["id"]


def test_weather_normalize_and_cache(client):
    w = client.get("/api/weather").json()
    assert w["current"]["temp"] == 54 and w["units"]["temp"] == "°F"
    assert w["hourly"][0]["time"] == "2026-11-05T09:00" and len(w["hourly"]) == 12
    assert len(w["daily"]) == 7
    client.get("/api/weather")
    assert client.calls == 1  # cached


def test_weather_offline_serves_stale(client):
    client.get("/api/weather")
    client.app.state.weather_cache["imperial"]["at"] = 0  # expire
    client.fail = True
    w = client.get("/api/weather").json()
    assert w["stale"] is True


def test_weather_unavailable(client):
    client.fail = True
    assert client.get("/api/weather").status_code == 502


def test_weather_units_param_cached_separately(client):
    assert client.get("/api/weather").json()["units"]["temp"] == "°F"
    assert client.get("/api/weather", params={"units": "metric"}).json()["units"]["temp"] == "°C"
    client.get("/api/weather"); client.get("/api/weather", params={"units": "metric"})
    assert client.calls == 2
    assert client.get("/api/weather", params={"units": "kelvin"}).status_code == 422


def test_member_update(client):
    a = client.post("/api/members", json={"name": "Mia"}).json()
    client.post("/api/members", json={"name": "Sam"})
    r = client.put(f"/api/members/{a['id']}", json={"name": "Mia R", "color": "#112233"}).json()
    assert r == {"id": a["id"], "name": "Mia R", "color": "#112233"}
    assert client.put(f"/api/members/{a['id']}", json={"name": "Mia R"}).json()["color"] == "#112233"  # keeps color
    assert client.put(f"/api/members/{a['id']}", json={"name": "Sam"}).status_code == 409
    assert client.put("/api/members/999", json={"name": "X"}).status_code == 404
