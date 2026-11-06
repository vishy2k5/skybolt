import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chores (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    due       TEXT,                      -- YYYY-MM-DD or NULL
    repeat    TEXT NOT NULL DEFAULT 'none',
    done      INTEGER NOT NULL DEFAULT 0,
    done_at   TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    start       TEXT NOT NULL,          -- ISO 8601 (date for all-day)
    end         TEXT NOT NULL,
    all_day     INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    calendar_id TEXT NOT NULL DEFAULT 'local',
    member_id   INTEGER REFERENCES members(id) ON DELETE SET NULL,
    repeat      TEXT NOT NULL DEFAULT 'none',  -- none|daily|weekly|monthly|yearly
    google_id   TEXT UNIQUE,            -- set once synced with Google
    etag        TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
"""


def connect(path: Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    for col, ddl in (("member_id", "INTEGER REFERENCES members(id) ON DELETE SET NULL"),
                     ("repeat", "TEXT NOT NULL DEFAULT 'none'")):
        if col not in cols:  # DB created before this column existed
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {ddl}")
    return conn
