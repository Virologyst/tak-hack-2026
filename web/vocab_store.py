"""SQLite behind, `taklib.voice.vocab.Vocabulary` in front.

This is the boundary. `taklib` stays pure standard library and knows nothing
about databases; everything sqlite-shaped lives here, on the web side.

The engine calls `load()` once per utterance. That is cheap on purpose: it
reads one indexed row from `meta` and returns the cached Vocabulary unless the
revision moved. Polling the DB rather than holding a dirty flag in memory
matters because `api.py` and `app.py` can both be running - a process-local
flag would go stale the moment the other process saved a term, and the engine
would keep using an old vocabulary with nothing on screen to say so.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schema  # noqa: E402  (sibling module, same directory)
from taklib.voice import takwords  # noqa: E402
from taklib.voice.vocab import Vocabulary, from_rows  # noqa: E402


class InvalidTakWord(ValueError):
    """A tak word that builds nothing. Carries suggestions so the UI can help."""

    def __init__(self, word: str):
        self.word = word
        self.suggestions = takwords.suggest(word)
        hint = (" Did you mean: %s?" % ", ".join(self.suggestions)
                if self.suggestions else
                " Leave it blank if this word has no TAK meaning, or use "
                "(ignore) to delete it from the transcript.")
        super().__init__(
            "'%s' is not a TAK term - it would build nothing and fail "
            "silently.%s" % (word, hint))

TERM_SQL = """
SELECT t.id, s.name AS service, t.trigger, t.tak_word, t.comments, t.service_id
  FROM terms t
  JOIN services s ON s.id = t.service_id
 ORDER BY s.sort_order, s.name, t.id
"""


class VocabStore:
    """Read/write access to services and terms, plus a cached Vocabulary."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or schema.DB_PATH
        self._cache: Optional[Vocabulary] = None
        self._cache_rev = -1

    def connect(self) -> sqlite3.Connection:
        return schema.connect(self.path)

    def migrate(self, *, seed: bool = True) -> dict:
        conn = self.connect()
        try:
            return schema.migrate(conn, seed=seed)
        finally:
            conn.close()

    # -- the engine's entry point -------------------------------------------

    def load(self) -> Vocabulary:
        """Current vocabulary, rebuilt only when the revision has moved."""
        conn = self.connect()
        try:
            rev = schema.revision(conn)
            if self._cache is not None and rev == self._cache_rev:
                return self._cache
            rows = [dict(r) for r in conn.execute(TERM_SQL)]
            self._cache = from_rows(rows, revision=rev)
            self._cache_rev = rev
            return self._cache
        finally:
            conn.close()

    def revision(self) -> int:
        conn = self.connect()
        try:
            return schema.revision(conn)
        finally:
            conn.close()

    # -- services ------------------------------------------------------------

    def list_services(self) -> List[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT s.id, s.name, s.team, s.is_core, s.sort_order, "
                "       COUNT(t.id) AS term_count "
                "  FROM services s LEFT JOIN terms t ON t.service_id = s.id "
                " GROUP BY s.id ORDER BY s.sort_order, s.name").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_service(self, name: str, team: str = "White",
                    sort_order: int = 100) -> Optional[dict]:
        name = (name or "").strip()
        if not name:
            return None
        conn = self.connect()
        try:
            conn.execute(
                "INSERT INTO services (name, team, sort_order) VALUES (?,?,?)",
                (name, team or "White", sort_order))
            conn.commit()
            schema.bump_revision(conn)
            row = conn.execute(
                "SELECT id, name, team, is_core, sort_order FROM services "
                " WHERE name = ?", (name,)).fetchone()
            return dict(row, term_count=0) if row else None
        except sqlite3.IntegrityError:
            return None                       # duplicate name
        finally:
            conn.close()

    def update_service(self, service_id: int, **fields) -> Optional[dict]:
        allowed = {"name", "team", "sort_order"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return None
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE services SET %s WHERE id = ?"
                % ", ".join("%s = ?" % k for k in sets),
                list(sets.values()) + [service_id])
            conn.commit()
            schema.bump_revision(conn)
            row = conn.execute(
                "SELECT id, name, team, is_core, sort_order FROM services "
                " WHERE id = ?", (service_id,)).fetchone()
            return dict(row) if row else None
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def delete_service(self, service_id: int) -> bool:
        """Delete a service and, by cascade, its terms. CORE is protected."""
        if int(service_id) == schema.CORE_SERVICE_ID:
            return False                      # core is the fallback; never goes
        conn = self.connect()
        try:
            cur = conn.execute("DELETE FROM services WHERE id = ? AND is_core = 0",
                               (service_id,))
            conn.commit()
            if cur.rowcount:
                schema.bump_revision(conn)
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- terms ---------------------------------------------------------------

    def list_terms(self, service_id: Optional[int] = None) -> List[dict]:
        conn = self.connect()
        try:
            if service_id is None:
                rows = conn.execute(TERM_SQL).fetchall()
            else:
                rows = conn.execute(
                    TERM_SQL.replace("ORDER BY", "WHERE t.service_id = ? ORDER BY"),
                    (service_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_term(self, service_id: int, trigger: str, tak_word: str = "",
                 comments: str = "") -> Optional[dict]:
        trigger = (trigger or "").strip()
        if not trigger:
            return None
        tak_word = (tak_word or "").strip()
        if not takwords.is_valid(tak_word):
            raise InvalidTakWord(tak_word)
        conn = self.connect()
        try:
            cur = conn.execute(
                "INSERT INTO terms (service_id, trigger, tak_word, comments) "
                "VALUES (?,?,?,?)",
                (service_id, trigger, tak_word, comments or ""))
            conn.commit()
            schema.bump_revision(conn)
            return self._get_term(conn, cur.lastrowid)
        except sqlite3.IntegrityError:
            # (service_id, trigger) is unique - the same word CAN exist in
            # another service, which is the entire point, but not twice here.
            return None
        finally:
            conn.close()

    def update_term(self, term_id: int, **fields) -> Optional[dict]:
        allowed = {"trigger", "tak_word", "comments", "service_id"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return None
        if "tak_word" in sets:
            sets["tak_word"] = (sets["tak_word"] or "").strip()
            if not takwords.is_valid(sets["tak_word"]):
                raise InvalidTakWord(sets["tak_word"])
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE terms SET %s, updated_at = datetime('now') WHERE id = ?"
                % ", ".join("%s = ?" % k for k in sets),
                list(sets.values()) + [term_id])
            conn.commit()
            schema.bump_revision(conn)
            return self._get_term(conn, term_id)
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def delete_term(self, term_id: int) -> bool:
        conn = self.connect()
        try:
            cur = conn.execute("DELETE FROM terms WHERE id = ?", (term_id,))
            conn.commit()
            if cur.rowcount:
                schema.bump_revision(conn)
            return cur.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def _get_term(conn: sqlite3.Connection, term_id: int) -> Optional[dict]:
        row = conn.execute(
            "SELECT t.id, s.name AS service, t.trigger, t.tak_word, t.comments, "
            "       t.service_id FROM terms t JOIN services s ON s.id=t.service_id "
            " WHERE t.id = ?", (term_id,)).fetchone()
        return dict(row) if row else None

    # -- bulk ----------------------------------------------------------------

    def export_json(self) -> dict:
        """The whole vocabulary as text.

        This is the disaster recovery story. A binary .db that gets clobbered
        by a bad merge is unrecoverable in the moment; a JSON file someone
        exported ten minutes ago is a twenty-second restore.
        """
        services: Dict[int, dict] = {}
        for svc in self.list_services():
            services[svc["id"]] = {"name": svc["name"], "team": svc["team"],
                                   "sort_order": svc["sort_order"], "terms": []}
        for term in self.list_terms():
            bucket = services.get(term["service_id"])
            if bucket is not None:
                bucket["terms"].append({"trigger": term["trigger"],
                                        "tak_word": term["tak_word"],
                                        "comments": term["comments"]})
        return {"services": list(services.values())}

    def import_json(self, payload: dict, *, replace: bool = False) -> dict:
        """Merge (or replace) a vocabulary from an exported payload."""
        conn = self.connect()
        added_services = added_terms = 0
        try:
            if replace:
                conn.execute("DELETE FROM terms")
                conn.execute("DELETE FROM services WHERE is_core = 0")

            for svc in payload.get("services", []):
                name = (svc.get("name") or "").strip()
                if not name:
                    continue
                if name.upper() == schema.CORE_SERVICE_NAME:
                    service_id = schema.CORE_SERVICE_ID
                else:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO services (name, team, sort_order) "
                        "VALUES (?,?,?)",
                        (name, svc.get("team", "White"), svc.get("sort_order", 100)))
                    added_services += cur.rowcount
                    service_id = conn.execute(
                        "SELECT id FROM services WHERE name = ?", (name,)
                    ).fetchone()["id"]

                for term in svc.get("terms", []):
                    trigger = (term.get("trigger") or "").strip()
                    if not trigger:
                        continue
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO terms "
                        "(service_id, trigger, tak_word, comments) VALUES (?,?,?,?)",
                        (service_id, trigger, term.get("tak_word", ""),
                         term.get("comments", "")))
                    added_terms += cur.rowcount
            conn.commit()
            schema.bump_revision(conn)
            return {"services": added_services, "terms": added_terms}
        finally:
            conn.close()


if __name__ == "__main__":                     # python web/vocab_store.py
    store = VocabStore()
    print("migrate:", store.migrate())
    for svc in store.list_services():
        print("  %-12s %-11s %2d terms" % (svc["name"], svc["team"],
                                           svc["term_count"]))
    print(json.dumps(store.export_json(), indent=2)[:400], "...")
