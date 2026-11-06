import pytest
from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.main import create_app


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", host="127.0.0.1", port=0, ui_dir=tmp_path / "none")
    with TestClient(create_app(s)) as c:
        yield c


EV = {"title": "Dentist", "start": "2026-11-06T09:00:00", "end": "2026-11-06T10:00:00"}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_crud(client):
    r = client.post("/api/events", json=EV)
    assert r.status_code == 201
    eid = r.json()["id"]
    assert client.get(f"/api/events/{eid}").json()["title"] == "Dentist"
    r = client.put(f"/api/events/{eid}", json={**EV, "title": "Dentist 2"})
    assert r.json()["title"] == "Dentist 2"
    assert client.delete(f"/api/events/{eid}").status_code == 204
    assert client.get(f"/api/events/{eid}").status_code == 404


def test_range_filter(client):
    client.post("/api/events", json=EV)
    client.post("/api/events", json={**EV, "title": "Later",
                "start": "2026-12-01T09:00:00", "end": "2026-12-01T10:00:00"})
    r = client.get("/api/events", params={"start": "2026-11-01T00:00:00", "end": "2026-11-30T00:00:00"})
    assert [e["title"] for e in r.json()] == ["Dentist"]


def test_validation(client):
    bad = {**EV, "end": "2026-11-06T08:00:00"}
    assert client.post("/api/events", json=bad).status_code == 422
    assert client.post("/api/events", json={**EV, "title": ""}).status_code == 422
