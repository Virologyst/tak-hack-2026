"""SQLite database for trigger phrases. The .db file ships with the repo."""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "triggers.db")

SEED = [
    ("mayday", "emergency"),
    ("officer down", "emergency"),
    ("on scene", "status"),
    ("requesting backup", "request"),
    ("all clear", "status"),
    ("crowd surge", "incident"),
]


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triggers (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            phrase   TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            category TEXT    NOT NULL DEFAULT 'custom'
        )
    """)
    for phrase, category in SEED:
        conn.execute(
            "INSERT OR IGNORE INTO triggers (phrase, category) VALUES (?, ?)",
            (phrase, category),
        )
    conn.commit()
    conn.close()


def all_triggers():
    conn = connect()
    rows = conn.execute("SELECT id, phrase, category FROM triggers ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_trigger(phrase, category="custom"):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO triggers (phrase, category) VALUES (?, ?)",
            (phrase.strip(), category),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, phrase, category FROM triggers WHERE phrase = ?",
            (phrase.strip(),),
        ).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        return None


def delete_trigger(trigger_id):
    conn = connect()
    cur = conn.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


if __name__ == "__main__":
    init()
    print("triggers.db ready — %d phrases" % len(all_triggers()))
    for t in all_triggers():
        print("  [%d] %-20s %s" % (t["id"], t["phrase"], t["category"]))
