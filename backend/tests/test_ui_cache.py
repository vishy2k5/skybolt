from fastapi.testclient import TestClient

from skybolt.config import Settings
from skybolt.main import create_app


def test_ui_files_are_revalidated(tmp_path):
    ui = tmp_path / "ui"
    (ui / "js").mkdir(parents=True)
    (ui / "index.html").write_text("<html></html>")
    (ui / "js" / "a.js").write_text("export {}")
    s = Settings(db_path=tmp_path / "t.db", host="127.0.0.1", port=0, ui_dir=ui)
    with TestClient(create_app(s)) as c:
        for path in ("/", "/js/a.js"):
            r = c.get(path)
            assert r.status_code == 200
            assert r.headers["cache-control"] == "no-cache"
