"""Google Cloud Firestore store.

Layout: `orbits/{pid}` holds the profile; each kind is a subcollection
`orbits/{pid}/{kind}/{doc_id}`. On Cloud Run the service account signs in by
itself, so no key file is needed anywhere.
"""

from __future__ import annotations

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .store import KINDS

ROOT = "orbits"


class FirestoreStore:
    def __init__(self, client: firestore.Client | None = None) -> None:
        self._db = client or firestore.Client()

    def _profile(self, pid: str):
        return self._db.collection(ROOT).document(pid)

    def _coll(self, pid: str, kind: str):
        return self._profile(pid).collection(kind)

    def create_profile(self, pid: str, doc: dict) -> bool:
        try:
            self._profile(pid).create(doc)
        except AlreadyExists:
            return False
        return True

    def get_profile(self, pid: str) -> dict | None:
        snap = self._profile(pid).get()
        return snap.to_dict() if snap.exists else None

    def update_profile(self, pid: str, patch: dict) -> None:
        self._profile(pid).set(patch, merge=True)

    def delete_profile(self, pid: str) -> None:
        for kind in KINDS:
            batch = self._db.batch()
            count = 0
            for snap in self._coll(pid, kind).limit(400).stream():
                batch.delete(snap.reference)
                count += 1
            if count:
                batch.commit()
        self._profile(pid).delete()

    def list_profile_ids(self) -> list[str]:
        return [ref.id for ref in self._db.collection(ROOT).list_documents()]

    def put(self, pid: str, kind: str, doc_id: str, doc: dict) -> None:
        self._coll(pid, kind).document(doc_id).set(doc)

    def create_if_absent(self, pid: str, kind: str, doc_id: str, doc: dict) -> bool:
        try:
            self._coll(pid, kind).document(doc_id).create(doc)
        except AlreadyExists:
            return False
        return True

    def get(self, pid: str, kind: str, doc_id: str) -> dict | None:
        snap = self._coll(pid, kind).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def delete(self, pid: str, kind: str, doc_id: str) -> None:
        self._coll(pid, kind).document(doc_id).delete()

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
        query = self._coll(pid, kind)
        if field:
            if lo is not None:
                query = query.where(filter=FieldFilter(field, ">=", lo))
            if hi is not None:
                query = query.where(filter=FieldFilter(field, "<=", hi))
            direction = firestore.Query.DESCENDING if newest_first else firestore.Query.ASCENDING
            query = query.order_by(field, direction=direction)
        if limit is not None:
            query = query.limit(limit)
        return [snap.to_dict() for snap in query.stream()]
