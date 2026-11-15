"""Storage. One elder's orbit is a profile document plus small collections.

`MemoryStore` is used for local runs and tests; `FirestoreStore` (Google Cloud
Firestore) is used in production. Both expose the same few methods.
"""

from __future__ import annotations

import copy
import threading
from typing import Protocol

KINDS = (
    "members",
    "medicines",
    "doses",
    "appointments",
    "notes",
    "feelings",
    "audit",
    "outbox",
)


class Store(Protocol):
    def create_profile(self, pid: str, doc: dict) -> bool: ...
    def get_profile(self, pid: str) -> dict | None: ...
    def update_profile(self, pid: str, patch: dict) -> None: ...
    def delete_profile(self, pid: str) -> None: ...
    def list_profile_ids(self) -> list[str]: ...
    def put(self, pid: str, kind: str, doc_id: str, doc: dict) -> None: ...
    def create_if_absent(self, pid: str, kind: str, doc_id: str, doc: dict) -> bool: ...
    def get(self, pid: str, kind: str, doc_id: str) -> dict | None: ...
    def delete(self, pid: str, kind: str, doc_id: str) -> None: ...
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
    ) -> list[dict]: ...


class MemoryStore:
    """Thread-safe in-process store. Data is lost when the process stops."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._profiles: dict[str, dict] = {}
        self._docs: dict[tuple[str, str], dict[str, dict]] = {}

    def create_profile(self, pid: str, doc: dict) -> bool:
        with self._lock:
            if pid in self._profiles:
                return False
            self._profiles[pid] = copy.deepcopy(doc)
            return True

    def get_profile(self, pid: str) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._profiles.get(pid))

    def update_profile(self, pid: str, patch: dict) -> None:
        with self._lock:
            if pid in self._profiles:
                self._profiles[pid].update(copy.deepcopy(patch))

    def delete_profile(self, pid: str) -> None:
        with self._lock:
            self._profiles.pop(pid, None)
            for key in [k for k in self._docs if k[0] == pid]:
                del self._docs[key]

    def list_profile_ids(self) -> list[str]:
        with self._lock:
            return list(self._profiles)

    def put(self, pid: str, kind: str, doc_id: str, doc: dict) -> None:
        with self._lock:
            self._docs.setdefault((pid, kind), {})[doc_id] = copy.deepcopy(doc)

    def create_if_absent(self, pid: str, kind: str, doc_id: str, doc: dict) -> bool:
        with self._lock:
            bucket = self._docs.setdefault((pid, kind), {})
            if doc_id in bucket:
                return False
            bucket[doc_id] = copy.deepcopy(doc)
            return True

    def get(self, pid: str, kind: str, doc_id: str) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._docs.get((pid, kind), {}).get(doc_id))

    def delete(self, pid: str, kind: str, doc_id: str) -> None:
        with self._lock:
            self._docs.get((pid, kind), {}).pop(doc_id, None)

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
        with self._lock:
            docs = [copy.deepcopy(d) for d in self._docs.get((pid, kind), {}).values()]
        if field:
            docs = [
                d
                for d in docs
                if d.get(field) is not None and (lo is None or d[field] >= lo) and (hi is None or d[field] <= hi)
            ]
            docs.sort(key=lambda d: d[field], reverse=newest_first)
        if limit is not None:
            docs = docs[:limit]
        return docs
