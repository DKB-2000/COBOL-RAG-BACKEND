import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from legacy_rag.api.dependencies import get_chunk_searcher, get_generation_model
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult

SECRET = "synthetic-sensitive-marker"
LOGGER = "legacy_rag.requests"


class EmptySearcher:
    def search(self, *, query, limit):
        return []


@pytest.mark.parametrize("case", ["ok", "validation", "unknown", "dependency_failure"])
def test_request_log_uses_only_safe_fields_and_server_generated_id(caplog, case):
    app = create_app()
    app.dependency_overrides[get_chunk_searcher] = EmptySearcher
    if case == "dependency_failure":
        def fail():
            raise RuntimeError(SECRET)
        app.dependency_overrides[get_chunk_searcher] = fail
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        if case == "unknown":
            response = client.get(f"/{SECRET}?token={SECRET}", headers={"X-Request-ID": SECRET})
        else:
            payload = {"query": SECRET, "limit": SECRET if case == "validation" else 5}
            response = client.post(
                f"/search?token={SECRET}", json=payload,
                headers={"X-Request-ID": SECRET, "Authorization": f"Bearer {SECRET}"},
            )

    expected = {"ok": 200, "validation": 422, "unknown": 404, "dependency_failure": 503}
    assert response.status_code == expected[case]
    assert SECRET not in response.text
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
    records = [json.loads(r.message) for r in caplog.records if r.name == LOGGER]
    assert len(records) == 1
    record = records[0]
    assert set(record) == {
        "event", "request_id", "method", "route", "status_code", "elapsed_ms", "error_kind",
        "query_status",
    }
    assert record["request_id"] == response.headers["X-Request-ID"]
    assert record["route"] == ("unmatched" if case == "unknown" else "/search")
    assert record["elapsed_ms"] >= 0
    assert SECRET not in caplog.text
    assert not any(r.exc_info for r in caplog.records)


def test_request_ids_are_distinct_and_query_status_is_logged_without_body(caplog):
    app = create_app()
    app.dependency_overrides[get_chunk_searcher] = EmptySearcher
    app.dependency_overrides[get_generation_model] = lambda: None
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        first = client.post("/query", json={"query": SECRET})
        second = client.get("/health")
    records = [json.loads(r.message) for r in caplog.records if r.name == LOGGER]
    assert records[0]["query_status"] == "refused"
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert SECRET not in caplog.text


def test_generation_failure_logs_only_unavailable_and_keeps_search_working(caplog):
    class SourceSearcher:
        def search(self, **kwargs):
            return [SearchResult("id", SECRET, "samples/a.cbl", "cobol", "A", "hash", 0, 0.5)]

    class FailedModel:
        def generate(self, request):
            raise TimeoutError(SECRET)

    app = create_app()
    app.dependency_overrides[get_chunk_searcher] = SourceSearcher
    app.dependency_overrides[get_generation_model] = FailedModel
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = client.post("/query", json={"query": SECRET})
        assert client.post("/search", json={"query": SECRET}).status_code == 200
    assert response.json()["status"] == "unavailable"
    assert SECRET not in response.text + caplog.text
    records = [json.loads(r.message) for r in caplog.records if r.name == LOGGER]
    assert records[0]["query_status"] == "unavailable"
