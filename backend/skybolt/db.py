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
    calendar_id TEXT NOT NULL DEFAULT 'local',   -- 'local' or a Google calendar id
    member_id   INTEGER REFERENCES members(id) ON DELETE SET NULL,
    repeat      TEXT NOT NULL DEFAULT 'none',  -- none|daily|weekly|monthly|yearly|custom
    rrule       TEXT NOT NULL DEFAULT '',      -- Google recurrence lines when repeat='custom'
    google_id   TEXT,                   -- set once synced with Google (unique per calendar)
    etag        TEXT,
    series_gid     TEXT,                -- one changed/cancelled occurrence of this Google series
    original_start TEXT,                -- ...replacing the occurrence that started here
    cancelled   INTEGER NOT NULL DEFAULT 0,
    pending     TEXT,                   -- 'upsert' | 'delete': local change not yet pushed to Google
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS google_calendars (
    id          TEXT PRIMARY KEY,
    summary     TEXT NOT NULL,
    color       TEXT NOT NULL DEFAULT '#4f9cf9',
    access_role TEXT NOT NULL DEFAULT 'reader',
    is_primary  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 0,
    sync_token  TEXT
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_google ON events(calendar_id, google_id);
CREATE INDEX IF NOT EXISTS idx_events_series ON events(calendar_id, series_gid);
"""

NEW_COLUMNS = (
    ("member_id", "INTEGER REFERENCES members(id) ON DELETE SET NULL"),
    ("repeat", "TEXT NOT NULL DEFAULT 'none'"),
    ("rrule", "TEXT NOT NULL DEFAULT ''"),
    ("series_gid", "TEXT"),
    ("original_start", "TEXT"),
    ("cancelled", "INTEGER NOT NULL DEFAULT 0"),
    ("pending", "TEXT"),
)


def _migrate_events(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    for col, ddl in NEW_COLUMNS:
        if col not in cols:  # DB created before this column existed
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {ddl}")
    # Older DBs had google_id UNIQUE; the same Google event can be in two calendars, so rebuild.
    if any(r["origin"] == "u" for r in conn.execute("PRAGMA index_list(events)")):
        names = ",".join(r["name"] for r in conn.execute("PRAGMA table_info(events)"))
        conn.execute("ALTER TABLE events RENAME TO events_old")
        conn.executescript(SCHEMA)
        conn.execute(f"INSERT INTO events ({names}) SELECT {names} FROM events_old")
        conn.execute("DROP TABLE events_old")
        conn.commit()


def connect(path: Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate_events(conn)
    conn.executescript(INDEXES)
    return conn
