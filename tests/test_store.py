"""The same storage contract holds for every backend."""

import pytest


def test_profile_lifecycle(store):
    assert store.create_profile("P1", {"elder_name": "A", "n": 1})
    assert not store.create_profile("P1", {"elder_name": "B"})
    store.update_profile("P1", {"n": 2, "extra": True})
    assert store.get_profile("P1") == {"elder_name": "A", "n": 2, "extra": True}
    assert "P1" in store.list_profile_ids()


def test_documents_and_range_queries(store):
    store.create_profile("P1", {})
    for day in ("2026-11-09", "2026-11-10", "2026-11-15", "2026-11-16"):
        store.put("P1", "notes", f"n_{day}", {"date": day, "text": day})
    found = store.list("P1", "notes", field="date", lo="2026-11-10", hi="2026-11-15")
    assert [d["date"] for d in found] == ["2026-11-10", "2026-11-15"]
    newest = store.list("P1", "notes", field="date", limit=2, newest_first=True)
    assert [d["date"] for d in newest] == ["2026-11-16", "2026-11-15"]
    assert len(store.list("P1", "notes")) == 4


def test_create_if_absent_is_exactly_once(store):
    store.create_profile("P1", {})
    assert store.create_if_absent("P1", "outbox", "k", {"n": 1})
    assert not store.create_if_absent("P1", "outbox", "k", {"n": 2})
    assert store.get("P1", "outbox", "k") == {"n": 1}


def test_delete_profile_removes_everything(store):
    store.create_profile("P1", {})
    store.put("P1", "members", "m", {"id": "m"})
    store.delete("P1", "members", "missing")
    store.delete_profile("P1")
    assert store.get_profile("P1") is None
    assert store.get("P1", "members", "m") is None
    assert "P1" not in store.list_profile_ids()


def test_profiles_are_isolated(store):
    store.create_profile("P1", {})
    store.create_profile("P2", {})
    store.put("P1", "notes", "n", {"date": "2026-11-15"})
    assert store.list("P2", "notes") == []


def test_unknown_query_fields_are_refused(store):
    if type(store).__name__ != "PostgresStore":
        pytest.skip("only the SQL store builds queries from field names")
    with pytest.raises(ValueError):
        store.list("P1", "notes", field="text; DROP TABLE orbit_docs")
