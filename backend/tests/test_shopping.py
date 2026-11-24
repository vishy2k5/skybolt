import pytest
from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.main import create_app


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", host="127.0.0.1", port=0, ui_dir=tmp_path / "none")
    with TestClient(create_app(s)) as c:
        yield c


def add(client, name, **kw):
    return client.post("/api/shopping", json={"name": name, **kw})


def names(client, **params):
    return [i["name"] for i in client.get("/api/shopping", params=params).json()]


def test_add_and_list_defaults_to_grocery(client):
    r = add(client, "  Milk ", note=" 2 litres ")
    assert r.status_code == 201
    assert r.json() | {"id": 0} == {"id": 0, "name": "Milk", "note": "2 litres", "list": "grocery", "done": False, "done_at": None}
    assert names(client) == ["Milk"]


def test_lists_are_separate(client):
    add(client, "Eggs")
    add(client, "Printer ink", list="order")
    assert names(client, list="grocery") == ["Eggs"]
    assert names(client, list="order") == ["Printer ink"]
    assert sorted(names(client)) == ["Eggs", "Printer ink"]
    assert client.get("/api/shopping", params={"list": "nope"}).status_code == 422


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {"name": "x" * 121}, {"name": "a", "note": "n" * 201},
                                  {"name": "a", "list": "other"}, {}])
def test_bad_items_rejected(client, body):
    assert client.post("/api/shopping", json=body).status_code == 422


def test_adding_a_duplicate_does_not_duplicate(client):
    first = add(client, "Milk").json()
    again = add(client, "  milk ")
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    assert names(client) == ["Milk"]
    # the same name on the other list is a different item
    assert add(client, "Milk", list="order").status_code == 201


def test_adding_a_checked_item_brings_it_back(client):
    i = add(client, "Bread").json()
    client.patch(f"/api/shopping/{i['id']}", json={"done": True})
    r = add(client, "bread").json()
    assert r["id"] == i["id"] and r["done"] is False and r["done_at"] is None


def test_duplicate_with_a_new_note_updates_the_note(client):
    i = add(client, "Apples", note="3").json()
    assert add(client, "apples", note="6").json()["note"] == "6"
    assert add(client, "apples").json()["note"] == "6"  # no note given: keep it
    assert client.get("/api/shopping").json()[0]["id"] == i["id"]


def test_check_and_uncheck_and_order(client):
    a, b, c = (add(client, n).json()["id"] for n in ("A", "B", "C"))
    client.patch(f"/api/shopping/{a}", json={"done": True})
    assert names(client) == ["B", "C", "A"]  # open first, checked last
    r = client.patch(f"/api/shopping/{a}", json={"done": False}).json()
    assert r["done"] is False and r["done_at"] is None
    assert names(client) == ["A", "B", "C"]
    done = client.patch(f"/api/shopping/{b}", json={"done": True}).json()
    assert done["done"] is True and done["done_at"]


def test_edit_and_move_between_lists(client):
    i = add(client, "Soap").json()["id"]
    r = client.put(f"/api/shopping/{i}", json={"name": "Hand soap", "note": "refill", "list": "order"})
    assert r.status_code == 200 and r.json()["list"] == "order" and r.json()["name"] == "Hand soap"
    assert names(client, list="grocery") == []
    add(client, "Tape")
    assert client.put(f"/api/shopping/{i}", json={"name": "tape", "list": "order"}).status_code == 200  # no clash on its own list
    assert client.put(f"/api/shopping/{i}", json={"name": "tape", "list": "grocery"}).status_code == 409  # clashes with Tape there


def test_delete_one_and_clear_checked(client):
    ids = [add(client, n).json()["id"] for n in ("A", "B", "C")]
    o = add(client, "Z", list="order").json()["id"]
    for i in (ids[0], ids[1], o):
        client.patch(f"/api/shopping/{i}", json={"done": True})
    assert client.delete("/api/shopping/done", params={"list": "grocery"}).json() == {"deleted": 2}
    assert names(client) == ["C", "Z"]  # the checked one on the other list stays
    assert client.delete(f"/api/shopping/{ids[2]}").status_code == 204
    assert client.delete(f"/api/shopping/{ids[2]}").status_code == 404
    assert client.delete("/api/shopping/done").json() == {"deleted": 1}
    assert names(client) == []


def test_unknown_item_is_404(client):
    assert client.patch("/api/shopping/99", json={"done": True}).status_code == 404
    assert client.put("/api/shopping/99", json={"name": "x"}).status_code == 404


def test_list_full(client, monkeypatch):
    monkeypatch.setattr("skybolt.shopping.MAX_ITEMS", 2)
    add(client, "a"); add(client, "b")
    assert add(client, "c").status_code == 422
    assert add(client, "c", list="order").status_code == 201
