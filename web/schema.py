"""Database schema for the voice console, and the migration onto it.

Separate from `db.py` deliberately. `db.py` is Craig's, it backs the original
trigger-phrase page, and that page keeps working: this migration reads the
`triggers` table and never drops it.

Two SQLite details worth knowing before changing anything here.

**`NULL != NULL` in a UNIQUE constraint.** The natural way to model core terms
is `service_id NULL` with `UNIQUE(service_id, trigger)` - and it silently fails,
because SQLite treats every NULL as distinct, so duplicate core terms pass the
constraint. The fix would be two partial indexes. Instead there is a real
`services` row with `id=1, is_core=1`: one plain unique index, no NULL branch in
any query, and far harder to get wrong at speed. `CORE_SERVICE_ID` must never be
deleted; the API blocks it.

**`PRAGMA foreign_keys` defaults to OFF, per connection.** Without it the
`ON DELETE CASCADE` below does nothing and deleting a service leaves its terms
orphaned - invisibly, since nothing errors. `connect()` sets it every time.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "triggers.db")
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed_vocab.json")

#: Bump when the DDL changes. `migrate()` is a no-op at or above this.
SCHEMA_VERSION = 2

#: The sentinel service holding terms that apply to every service.
CORE_SERVICE_ID = 1
CORE_SERVICE_NAME = "CORE"

DDL = """
CREATE TABLE IF NOT EXISTS services (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    team       TEXT    NOT NULL DEFAULT 'White',
    is_core    INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS terms (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL DEFAULT 1
               REFERENCES services(id) ON DELETE CASCADE,
    trigger    TEXT    NOT NULL COLLATE NOCASE,
    tak_word   TEXT    NOT NULL DEFAULT '',
    comments   TEXT    NOT NULL DEFAULT '',
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (service_id, trigger)
);
CREATE INDEX IF NOT EXISTS ix_terms_service ON terms(service_id);

CREATE TABLE IF NOT EXISTS servers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    url        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    kind       TEXT    NOT NULL DEFAULT 'manual',
    chat_url   TEXT    NOT NULL DEFAULT '',
    -- Which vocabulary this server listens with. NULL means core terms only.
    -- Per-server rather than global because one machine may bridge a police
    -- net to one server and an ambulance net to another, and "fire" has to
    -- mean different things on each.
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
    callsign   TEXT    NOT NULL DEFAULT '',
    team       TEXT    NOT NULL DEFAULT 'Cyan',
    uid_prefix TEXT    NOT NULL DEFAULT 'voice',
    lat        REAL,
    lon        REAL,
    stale      REAL    NOT NULL DEFAULT 300,
    cert       TEXT    NOT NULL DEFAULT '',
    key_file   TEXT    NOT NULL DEFAULT '',
    verify_tls INTEGER NOT NULL DEFAULT 1,
    notes      TEXT    NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 0,
    last_seen  TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audio_profiles (
    device      INTEGER PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    gain        REAL NOT NULL DEFAULT 1.0,
    threshold   REAL NOT NULL DEFAULT 0.015,
    hangover    REAL NOT NULL DEFAULT 0.15,
    zcr_max     REAL NOT NULL DEFAULT 0.0,
    hard_split  REAL NOT NULL DEFAULT 0.0,
    max_seconds REAL NOT NULL DEFAULT 15.0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    """A connection with the pragmas this schema depends on."""
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    # Without this the ON DELETE CASCADE above is decorative.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def bump_revision(conn: sqlite3.Connection) -> int:
    """Record that the vocabulary changed, so the engine reloads it.

    Kept in the DB rather than in memory because `api.py` and `app.py` can both
    be running - a process-local dirty flag would go stale the moment the other
    process wrote a term, and the engine would keep using an old vocabulary with
    nothing on screen to say so.
    """
    row = conn.execute(
        "SELECT value FROM meta WHERE key='vocab_revision'").fetchone()
    nxt = (int(row["value"]) if row else 0) + 1
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('vocab_revision', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(nxt),))
    conn.commit()
    return nxt


def revision(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM meta WHERE key='vocab_revision'").fetchone()
    return int(row["value"]) if row else 0


def migrate(conn: sqlite3.Connection, *, seed: bool = True) -> dict:
    """Bring a database up to SCHEMA_VERSION. Idempotent; safe every start.

    Returns a small report so the caller can print what happened rather than
    guessing.
    """
    report = {"created": False, "migrated_triggers": 0, "seeded": 0,
              "from_version": 0, "to_version": SCHEMA_VERSION}

    current = conn.execute("PRAGMA user_version").fetchone()[0]
    report["from_version"] = current
    if current >= SCHEMA_VERSION:
        report["to_version"] = current
        return report

    conn.executescript(DDL)
    report["created"] = True

    conn.execute(
        "INSERT OR IGNORE INTO services (id, name, team, is_core, sort_order) "
        "VALUES (?, ?, 'White', 1, 0)", (CORE_SERVICE_ID, CORE_SERVICE_NAME))

    terms_empty = conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 0

    # Carry Craig's phrases across as core terms. tak_word = phrase is an
    # identity mapping: lossless, unsurprising, and immediately editable. The
    # old category is not thrown away, it becomes a comment.
    if terms_empty and _table_exists(conn, "triggers"):
        cur = conn.execute(
            "INSERT OR IGNORE INTO terms (service_id, trigger, tak_word, comments) "
            "SELECT ?, phrase, phrase, 'migrated from category=' || category "
            "FROM triggers", (CORE_SERVICE_ID,))
        report["migrated_triggers"] = cur.rowcount

    # Seed on "no services yet", NOT "no terms yet". The triggers migration
    # above only ever fills CORE, so gating the seed on an empty terms table
    # meant a repo shipping triggers.db never got the per-service examples -
    # and the per-service case is the whole point of the feature. The two are
    # complementary: triggers become core terms, the seed adds the services.
    no_services = conn.execute(
        "SELECT COUNT(*) FROM services WHERE is_core = 0").fetchone()[0] == 0
    if seed and no_services:
        report["seeded"] = _apply_seed(conn)

    bump_revision(conn)
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.commit()
    return report


def _apply_seed(conn: sqlite3.Connection) -> int:
    """Load `seed_vocab.json` if present, so a cold clone has something to show.

    The seed is tracked TEXT rather than a binary database: text merges when two
    people edit it, and a binary .db does not.
    """
    if not os.path.exists(SEED_PATH):
        return 0
    try:
        with open(SEED_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return 0

    added = 0
    for svc in payload.get("services", []):
        name = (svc.get("name") or "").strip()
        if not name:
            continue
        if name.upper() == CORE_SERVICE_NAME:
            service_id = CORE_SERVICE_ID
        else:
            conn.execute(
                "INSERT OR IGNORE INTO services (name, team, sort_order) "
                "VALUES (?, ?, ?)",
                (name, svc.get("team", "White"), svc.get("sort_order", 100)))
            row = conn.execute(
                "SELECT id FROM services WHERE name = ?", (name,)).fetchone()
            service_id = row["id"]

        for term in svc.get("terms", []):
            trigger = (term.get("trigger") or "").strip()
            if not trigger:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO terms (service_id, trigger, tak_word, comments) "
                "VALUES (?, ?, ?, ?)",
                (service_id, trigger, term.get("tak_word", ""),
                 term.get("comments", "")))
            added += cur.rowcount
    return added


if __name__ == "__main__":                       # python web/schema.py
    conn = connect()
    report = migrate(conn)
    print("schema v%d -> v%d" % (report["from_version"], report["to_version"]))
    if report["migrated_triggers"]:
        print("  carried %d phrase(s) over from the triggers table"
              % report["migrated_triggers"])
    if report["seeded"]:
        print("  seeded %d term(s) from seed_vocab.json" % report["seeded"])
    for row in conn.execute(
            "SELECT s.name, COUNT(t.id) n FROM services s "
            "LEFT JOIN terms t ON t.service_id = s.id "
            "GROUP BY s.id ORDER BY s.sort_order, s.name"):
        print("  %-14s %d term(s)" % (row["name"], row["n"]))
    conn.close()
