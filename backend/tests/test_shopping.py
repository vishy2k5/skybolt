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
    cleared = client.delete("/api/shopping/done", params={"list": "grocery"}).json()
    assert cleared["deleted"] == 2 and [i["name"] for i in cleared["items"]] == ["A", "B"] and all(i["done"] for i in cleared["items"])
    assert names(client) == ["C", "Z"]  # the checked one on the other list stays
    assert client.delete(f"/api/shopping/{ids[2]}").status_code == 204
    assert client.delete(f"/api/shopping/{ids[2]}").status_code == 404
    assert client.delete("/api/shopping/done").json()["deleted"] == 1
    assert names(client) == []


def test_unknown_item_is_404(client):
    assert client.patch("/api/shopping/99", json={"done": True}).status_code == 404
    assert client.put("/api/shopping/99", json={"name": "x"}).status_code == 404


def test_list_full(client, monkeypatch):
    monkeypatch.setattr("skybolt.shopping.MAX_ITEMS", 2)
    add(client, "a"); add(client, "b")
    assert add(client, "c").status_code == 422
    assert add(client, "c", list="order").status_code == 201


# ---- suggestions ------------------------------------------------------------------------------------------------------

def sug(client):
    return client.get("/api/shopping/suggestions").json()


def test_suggestions_start_empty(client):
    assert sug(client) == {"grocery": [], "order": []}


def test_things_on_the_list_are_not_suggested_but_cleared_ones_are(client):
    a = add(client, "Milk").json()["id"]
    add(client, "Eggs")
    assert sug(client)["grocery"] == []  # both are on the list already
    client.patch(f"/api/shopping/{a}", json={"done": True})
    assert sug(client)["grocery"] == []  # checked but still listed
    client.delete("/api/shopping/done")
    assert sug(client)["grocery"] == ["Milk"]
    add(client, "milk")
    assert sug(client)["grocery"] == []


def test_suggestions_are_per_list_and_most_used_first(client):
    for _ in range(3):  # buy Bread three times, Jam once
        i = add(client, "Bread").json()["id"]
        client.patch(f"/api/shopping/{i}", json={"done": True})
        client.delete("/api/shopping/done")
    j = add(client, "Jam").json()["id"]
    k = add(client, "Cable", list="order").json()["id"]
    for i in (j, k):
        client.patch(f"/api/shopping/{i}", json={"done": True})
    client.delete("/api/shopping/done")
    assert sug(client) == {"grocery": ["Bread", "Jam"], "order": ["Cable"]}


def test_deleting_an_item_forgets_it_but_clearing_does_not(client):
    typo = add(client, "Mlik").json()["id"]
    client.delete(f"/api/shopping/{typo}")
    assert sug(client)["grocery"] == []
    ok = add(client, "Milk").json()["id"]
    client.patch(f"/api/shopping/{ok}", json={"done": True})
    client.delete("/api/shopping/done")
    assert sug(client)["grocery"] == ["Milk"]


def test_fixing_a_typo_replaces_the_suggestion(client):
    i = add(client, "Mlik").json()["id"]
    client.put(f"/api/shopping/{i}", json={"name": "Milk"})
    client.patch(f"/api/shopping/{i}", json={"done": True})
    client.delete("/api/shopping/done")
    assert sug(client)["grocery"] == ["Milk"]  # not "Mlik" as well


def test_moving_an_item_moves_the_suggestion(client):
    i = add(client, "Soap").json()["id"]
    client.put(f"/api/shopping/{i}", json={"name": "Soap", "list": "order"})
    client.patch(f"/api/shopping/{i}", json={"done": True})
    client.delete("/api/shopping/done")
    assert sug(client) == {"grocery": [], "order": ["Soap"]}


def test_buying_a_checked_item_again_counts_as_a_use(client):
    for n in ("A", "B"):
        i = add(client, n).json()["id"]
        client.patch(f"/api/shopping/{i}", json={"done": True})
    add(client, "B")  # bought again: B now outranks A
    client.patch(f"/api/shopping/{client.get('/api/shopping').json()[0]['id']}", json={"done": True})
    client.delete("/api/shopping/done")
    assert sug(client)["grocery"] == ["B", "A"]


def test_history_is_capped(client, monkeypatch):
    monkeypatch.setattr("skybolt.shopping.HISTORY_MAX", 2)
    for n in ("a", "b", "c"):
        i = add(client, n).json()["id"]
        client.patch(f"/api/shopping/{i}", json={"done": True})
    client.delete("/api/shopping/done")
    assert len(sug(client)["grocery"]) == 2
