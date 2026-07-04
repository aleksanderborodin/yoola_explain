"""SQLite system of record (L3). No full source text is ever stored (Design v4 C10):
only hashes, the SimHash, the keyword-hit map, and the summary JSON (which
contains short verbatim quotes)."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from .identity import hamming
from .schema import SummaryDoc

DDL = """
CREATE TABLE IF NOT EXISTS urls (
  url_key      TEXT PRIMARY KEY,
  doc_version  TEXT NOT NULL,
  final_url    TEXT,
  first_seen   TEXT NOT NULL,
  last_checked TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS doc_versions (
  doc_version     TEXT PRIMARY KEY,
  simhash         TEXT NOT NULL,
  content_chars   INTEGER NOT NULL,
  source_language TEXT NOT NULL,
  source_verified INTEGER NOT NULL,
  keyword_map     TEXT NOT NULL,
  first_seen      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aliases (
  alias        TEXT PRIMARY KEY,
  doc_version  TEXT NOT NULL REFERENCES doc_versions(doc_version)
);
CREATE TABLE IF NOT EXISTS summaries (
  doc_version   TEXT PRIMARY KEY REFERENCES doc_versions(doc_version),
  summary_json  TEXT NOT NULL,
  model_version TEXT NOT NULL,
  generated_at  TEXT NOT NULL,
  demoted       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS translations (
  doc_version  TEXT NOT NULL REFERENCES doc_versions(doc_version),
  language     TEXT NOT NULL,
  strings_json TEXT NOT NULL,
  PRIMARY KEY (doc_version, language)
);
CREATE TABLE IF NOT EXISTS flags (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_version TEXT NOT NULL,
  category    TEXT,
  reason      TEXT,
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
  day    TEXT NOT NULL,
  scope  TEXT NOT NULL,
  count  INTEGER NOT NULL,
  PRIMARY KEY (day, scope)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """One connection, WAL, guarded by a lock — plenty for the MVP single process."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(DDL)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # -- urls ------------------------------------------------------------

    def get_url_entry(self, url_key: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM urls WHERE url_key = ?", (url_key,)
            ).fetchone()

    def url_entry_fresh(self, entry: sqlite3.Row, ttl_days: int) -> bool:
        last = datetime.fromisoformat(entry["last_checked"])
        return datetime.now(timezone.utc) - last < timedelta(days=ttl_days)

    def map_url(self, url_key: str, doc_version: str, final_url: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO urls (url_key, doc_version, final_url, first_seen, last_checked)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(url_key) DO UPDATE
                   SET doc_version = excluded.doc_version,
                       final_url = excluded.final_url,
                       last_checked = excluded.last_checked""",
                (url_key, doc_version, final_url, _now(), _now()),
            )

    def touch_url(self, url_key: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE urls SET last_checked = ? WHERE url_key = ?", (_now(), url_key)
            )

    # -- doc versions & summaries ----------------------------------------

    def resolve_doc_version(self, doc_version: str) -> str:
        """Follow a near-dup alias to its canonical doc_version, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_version FROM aliases WHERE alias = ?", (doc_version,)
            ).fetchone()
        return row["doc_version"] if row else doc_version

    def get_doc_version(self, doc_version: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM doc_versions WHERE doc_version = ?", (doc_version,)
            ).fetchone()

    def add_doc_version(
        self,
        doc_version: str,
        simhash: int,
        content_chars: int,
        source_language: str,
        source_verified: bool,
        keyword_map: dict[str, list[str]],
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO doc_versions
                   (doc_version, simhash, content_chars, source_language,
                    source_verified, keyword_map, first_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_version,
                    format(simhash, "016x"),
                    content_chars,
                    source_language,
                    int(source_verified),
                    json.dumps(keyword_map),
                    _now(),
                ),
            )

    def mark_source_verified(self, doc_version: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE doc_versions SET source_verified = 1 WHERE doc_version = ?",
                (doc_version,),
            )

    def add_alias(self, alias: str, doc_version: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO aliases (alias, doc_version) VALUES (?, ?)",
                (alias, doc_version),
            )

    def save_summary(self, doc: SummaryDoc) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO summaries
                   (doc_version, summary_json, model_version, generated_at, demoted)
                   VALUES (?, ?, ?, ?, 0)""",
                (
                    doc.doc_version,
                    doc.model_dump_json(),
                    doc.model_version,
                    doc.generated_at.isoformat(),
                ),
            )

    def get_summary(self, doc_version: str, include_demoted: bool = False) -> SummaryDoc | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT summary_json, demoted FROM summaries WHERE doc_version = ?",
                (doc_version,),
            ).fetchone()
        if row is None or (row["demoted"] and not include_demoted):
            return None
        return SummaryDoc.model_validate_json(row["summary_json"])

    def find_near_duplicate(
        self, simhash: int, max_distance: int, verified_only: bool = True
    ) -> tuple[str, dict[str, list[str]]] | None:
        """Nearest stored doc_version (with a live summary) within max_distance.

        Linear scan over stored signatures — fine into the tens of thousands of
        documents; index it when that stops being true (docs/roadmap.md).
        """
        query = """SELECT d.doc_version, d.simhash, d.keyword_map
                   FROM doc_versions d JOIN summaries s ON s.doc_version = d.doc_version
                   WHERE s.demoted = 0"""
        if verified_only:
            query += " AND d.source_verified = 1"
        with self._lock:
            rows = self._conn.execute(query).fetchall()
        best: tuple[int, sqlite3.Row] | None = None
        for row in rows:
            distance = hamming(simhash, int(row["simhash"], 16))
            if distance <= max_distance and (best is None or distance < best[0]):
                best = (distance, row)
        if best is None:
            return None
        return best[1]["doc_version"], json.loads(best[1]["keyword_map"])

    # -- translations ------------------------------------------------------

    def get_translation(self, doc_version: str, language: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT strings_json FROM translations WHERE doc_version = ? AND language = ?",
                (doc_version, language),
            ).fetchone()
        return json.loads(row["strings_json"]) if row else None

    def save_translation(self, doc_version: str, language: str, strings: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO translations (doc_version, language, strings_json)
                   VALUES (?, ?, ?)""",
                (doc_version, language, json.dumps(strings)),
            )

    # -- flags / demotion --------------------------------------------------

    def add_flag(self, doc_version: str, category: str | None, reason: str | None) -> int:
        """Record a report; returns the total flag count for the doc_version."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO flags (doc_version, category, reason, created_at) VALUES (?, ?, ?, ?)",
                (doc_version, category, reason, _now()),
            )
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM flags WHERE doc_version = ?", (doc_version,)
            ).fetchone()
        return row["n"]

    def demote_summary(self, doc_version: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE summaries SET demoted = 1 WHERE doc_version = ?", (doc_version,)
            )

    # -- budgets -------------------------------------------------------------

    def increment_budget(self, scope: str) -> int:
        """Increment today's counter for scope ('global' or 'ip:<addr>'); return new value."""
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO budgets (day, scope, count) VALUES (?, ?, 1)
                   ON CONFLICT(day, scope) DO UPDATE SET count = count + 1""",
                (day, scope),
            )
            row = self._conn.execute(
                "SELECT count FROM budgets WHERE day = ? AND scope = ?", (day, scope)
            ).fetchone()
        return row["count"]

    def get_budget(self, scope: str) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM budgets WHERE day = ? AND scope = ?", (day, scope)
            ).fetchone()
        return row["count"] if row else 0
