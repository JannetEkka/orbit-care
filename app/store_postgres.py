"""PostgreSQL store (used on Render). Same interface as MemoryStore and FirestoreStore.

Two tables of JSON documents: one row per elder's profile, and one row per
document in a profile's collections. Range queries compare ISO date strings
with the "C" collation, so they sort exactly like the other stores.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .store import KINDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS orbit_profiles (
    pid TEXT PRIMARY KEY,
    doc JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS orbit_docs (
    pid TEXT NOT NULL REFERENCES orbit_profiles(pid) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc JSONB NOT NULL,
    PRIMARY KEY (pid, kind, doc_id)
);
"""
# Only these fields are ever used for range queries; the name is never taken from a request.
RANGE_FIELDS = {"date", "at", "created_at"}


class PostgresStore:
    def __init__(self, url: str, pool: ConnectionPool | None = None) -> None:
        self._pool = pool or ConnectionPool(url, min_size=1, max_size=4, open=True, kwargs={"autocommit": True})
        with self._pool.connection() as conn:
            conn.execute(SCHEMA)

    def close(self) -> None:
        self._pool.close()

    def create_profile(self, pid: str, doc: dict) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO orbit_profiles (pid, doc) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING 1",
                (pid, Jsonb(doc)),
            ).fetchone()
        return row is not None

    def get_profile(self, pid: str) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT doc FROM orbit_profiles WHERE pid = %s", (pid,)).fetchone()
        return row[0] if row else None

    def update_profile(self, pid: str, patch: dict) -> None:
        with self._pool.connection() as conn:
            conn.execute("UPDATE orbit_profiles SET doc = doc || %s WHERE pid = %s", (Jsonb(patch), pid))

    def delete_profile(self, pid: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM orbit_profiles WHERE pid = %s", (pid,))

    def list_profile_ids(self) -> list[str]:
        with self._pool.connection() as conn:
            return [row[0] for row in conn.execute("SELECT pid FROM orbit_profiles").fetchall()]

    def put(self, pid: str, kind: str, doc_id: str, doc: dict) -> None:
        assert kind in KINDS
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO orbit_docs (pid, kind, doc_id, doc) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (pid, kind, doc_id) DO UPDATE SET doc = EXCLUDED.doc",
                (pid, kind, doc_id, Jsonb(doc)),
            )

    def create_if_absent(self, pid: str, kind: str, doc_id: str, doc: dict) -> bool:
        assert kind in KINDS
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO orbit_docs (pid, kind, doc_id, doc) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING 1",
                (pid, kind, doc_id, Jsonb(doc)),
            ).fetchone()
        return row is not None

    def get(self, pid: str, kind: str, doc_id: str) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT doc FROM orbit_docs WHERE pid = %s AND kind = %s AND doc_id = %s", (pid, kind, doc_id)
            ).fetchone()
        return row[0] if row else None

    def delete(self, pid: str, kind: str, doc_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM orbit_docs WHERE pid = %s AND kind = %s AND doc_id = %s", (pid, kind, doc_id))

    def list(
        self,
        pid: str,
        kind: str,
        *,
        field: str | None = None,
        lo: str | None = None,
        hi: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[dict]:
        sql = "SELECT doc FROM orbit_docs WHERE pid = %s AND kind = %s"
        params: list = [pid, kind]
        if field:
            if field not in RANGE_FIELDS:
                raise ValueError(f"Unsupported query field: {field}")
            value = f"(doc->>'{field}') COLLATE \"C\""
            sql += f" AND doc ? '{field}'"
            if lo is not None:
                sql += f" AND {value} >= %s"
                params.append(lo)
            if hi is not None:
                sql += f" AND {value} <= %s"
                params.append(hi)
            sql += f" ORDER BY {value} {'DESC' if newest_first else 'ASC'}"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(int(limit))
        with self._pool.connection() as conn:
            return [row[0] for row in conn.execute(sql, params).fetchall()]
