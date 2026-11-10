import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from skybolt.config import Settings
from skybolt.main import create_app


def save(path, size=(400, 300), fmt="JPEG", exif=None, color=(200, 80, 40)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, fmt, **({"exif": exif} if exif else {}))


@pytest.fixture
def env(tmp_path):
    photos = tmp_path / "photos"
    s = Settings(db_path=tmp_path / "data" / "t.db", host="127.0.0.1", port=0, ui_dir=tmp_path / "none", photos_dir=photos, photo_max=200)
    with TestClient(create_app(s)) as c:
        yield c, photos, tmp_path / "data" / "photo_cache"


def served(c, pid):
    r = c.get(f"/api/photos/{pid}")
    assert r.status_code == 200
    return r, Image.open(io.BytesIO(r.content))


def test_empty_or_missing_folder(env):
    c, photos, _ = env
    assert c.get("/api/photos").json() == []  # folder does not exist yet
    photos.mkdir()
    assert c.get("/api/photos").json() == []


def test_lists_only_real_pictures_and_skips_hidden_files(env):
    c, photos, _ = env
    save(photos / "a.jpg"); save(photos / "b.PNG", fmt="PNG"); save(photos / "trip" / "c.jpeg"); save(photos / "d.webp", fmt="WEBP")
    save(photos / "._a.jpg")                       # macOS AppleDouble copy: not a real image
    (photos / ".DS_Store").write_bytes(b"x"); (photos / "notes.txt").write_text("hi")
    save(photos / ".hidden" / "e.jpg")
    assert len(c.get("/api/photos").json()) == 4


def test_resized_upright_and_stripped(env):
    c, photos, _ = env
    exif = Image.Exif(); exif[0x0112] = 6; exif[0x010F] = "SecretCamera"  # rotate 90, plus a maker name
    save(photos / "phone.jpg", size=(1200, 800), exif=exif)
    pid = c.get("/api/photos").json()[0]
    r, im = served(c, pid)
    assert r.headers["content-type"] == "image/jpeg" and "immutable" in r.headers["cache-control"]
    assert im.size == (133, 200) or im.size == (134, 200)  # 1200x800 turned upright (800x1200), longest side capped at 200
    assert not dict(im.getexif())                      # no EXIF left: orientation applied, no camera or location data


def test_small_pictures_are_not_enlarged(env):
    c, photos, _ = env
    save(photos / "small.jpg", size=(100, 60))
    _, im = served(c, c.get("/api/photos").json()[0])
    assert im.size == (100, 60)


def test_corrupt_file_is_listed_but_404_and_not_retried(env):
    c, photos, _ = env
    photos.mkdir(); (photos / "broken.jpg").write_bytes(b"not an image")
    pid = c.get("/api/photos").json()[0]
    assert c.get(f"/api/photos/{pid}").status_code == 404
    assert c.get(f"/api/photos/{pid}").status_code == 404
    assert pid in c.app.state.photo_bad


def test_unknown_ids_and_path_tricks_never_touch_the_disk(env):
    c, photos, _ = env
    save(photos / "a.jpg")
    for bad in ("nope", "..%2F..%2Fetc%2Fpasswd", "....", "a.jpg", "0" * 20):
        assert c.get(f"/api/photos/{bad}").status_code == 404


def test_new_file_is_found_without_waiting_for_the_scan_to_expire(env):
    c, photos, _ = env
    save(photos / "a.jpg")
    first = c.get("/api/photos").json()
    save(photos / "b.jpg", color=(10, 200, 10))        # copied in after the last scan
    ids = c.get("/api/photos").json()
    new = (set(ids) - set(first)).pop()
    assert c.get(f"/api/photos/{new}").status_code == 200


def test_replacing_a_file_changes_its_id_and_stale_cache_is_removed(env):
    c, photos, cache = env
    save(photos / "a.jpg", color=(1, 2, 3))
    old = c.get("/api/photos").json()[0]
    served(c, old)
    assert (cache / f"{old}-200.jpg").exists()
    save(photos / "a.jpg", size=(500, 500), color=(9, 9, 9))
    new = c.get("/api/photos").json()[0]
    assert new != old and not (cache / f"{old}-200.jpg").exists()  # old copy cleaned up
    served(c, new)


def test_deleted_file_disappears_and_its_cache_goes(env):
    c, photos, cache = env
    save(photos / "a.jpg"); save(photos / "b.jpg", color=(5, 5, 5))
    ids = c.get("/api/photos").json()
    for i in ids:
        served(c, i)
    (photos / "a.jpg").unlink()
    left = c.get("/api/photos").json()
    assert len(left) == 1 and len(list(cache.glob("*.jpg"))) == 1
