import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from time import sleep

import pytest
from fastapi.testclient import TestClient

from legacy_rag.api import dependencies
from legacy_rag.api.public_corpus import load_public_chunks
from legacy_rag.generation.models import AnswerClaim, GeneratedAnswer
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult


class Source:
    def __init__(self, rows):
        self.rows, self.limits = rows, []

    def search(self, *, query, limit):
        self.limits.append(limit)
        return self.rows[:limit]


class Ranker:
    def __init__(self):
        self.calls = []

    def rank(self, query, candidates):
        self.calls.append(list(candidates))
        return candidates


class Model:
    def __init__(self):
        self.requests = []

    def generate(self, request):
        payload = json.loads(request.user_prompt)
        self.requests.append(payload)
        return GeneratedAnswer(status="answered", claims=[AnswerClaim(
            text="확인했다.", chunk_ids=[payload["context"][-1]["chunk_id"]],
        )])


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_RERANKING", "bge-int8")
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "disabled")
    rows = [SearchResult(f"c{i}", "x" * 4001 if i == 0 else f"code{i}",
                         "samples/a.cbl", "cobol", "A", "h", i, .5) for i in range(40)]
    source, ranker, model = Source(rows), Ranker(), Model()
    dependencies.get_chunk_searcher.cache_clear()
    dependencies._get_reranker.cache_clear()
    monkeypatch.setattr(dependencies, "get_chunk_store", lambda: object())
    monkeypatch.setattr(dependencies, "get_embedding_function", lambda: object())
    monkeypatch.setattr(dependencies, "VectorChunkSearcher", lambda **kwargs: source)
    monkeypatch.setattr(dependencies, "LocalBgeReranker", lambda path: ranker)
    app = create_app()
    app.dependency_overrides[dependencies.get_generation_model] = lambda: model
    with TestClient(app) as client:
        yield client, source, ranker, model
    dependencies.get_chunk_searcher.cache_clear()
    dependencies._get_reranker.cache_clear()


def test_default_is_enabled_and_model_path_is_pinned(monkeypatch):
    monkeypatch.delenv("LEGACY_RAG_RERANKING", raising=False)
    settings = dependencies.ApiSettings()
    assert settings.reranking == "bge-int8"
    assert settings.reranker_model_dir.name == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def test_search_reranks_candidates_before_response_limit(harness):
    client, source, ranker, _ = harness
    response = client.post("/search", json={"query": "?", "limit": 2})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert source.limits == [30] and len(ranker.calls[0]) == 30
    assert response.json()["results"][0]["score"] == .5


def test_query_assembles_from_thirty_before_count_and_character_limit(harness):
    client, source, ranker, model = harness
    response = client.post("/query", json={"query": "?"})
    assert response.json()["status"] == "answered"
    context = model.requests[0]["context"]
    assert [row["chunk_id"] for row in context] == [f"c{i}" for i in range(1, 11)]
    assert sum(len(row["text"]) for row in context) <= 4000
    assert source.limits == [30] and len(ranker.calls) == 1


def test_disabled_restores_original_search_without_loading_ranker(harness, monkeypatch):
    client, source, ranker, _ = harness
    monkeypatch.setenv("LEGACY_RAG_RERANKING", "disabled")
    response = client.post("/search", json={"query": "?", "limit": 2})
    assert response.status_code == 200 and source.limits == [2]
    assert ranker.calls == []


def test_public_guard_runs_before_context_selection(harness, monkeypatch):
    client, source, _, model = harness
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    public = [SearchResult(**asdict(chunk), score=.5)
              for chunk in load_public_chunks(dependencies.ApiSettings().data_root).values()
              if len(chunk.text) < 120][:12]
    assert len(public) == 12
    source.rows = [SearchResult(f"private{i}", "PRIVATE-LOCAL", "raw/private.cbl",
                                "cobol", "A", "h", i, .9) for i in range(18)] + public
    response = client.post("/query", json={"query": "?"})
    assert response.json()["status"] == "answered"
    assert len(model.requests[0]["context"]) == 10
    assert "PRIVATE-LOCAL" not in json.dumps(model.requests)


def test_ranker_failure_is_safe_503_and_never_calls_generation(harness, monkeypatch, caplog):
    client, _, ranker, model = harness

    def fail(*args):
        raise RuntimeError("synthetic-private-model-path")

    monkeypatch.setattr(ranker, "rank", fail)
    for route, method in (("/search", "post"), ("/query", "post"), ("/ready", "get")):
        response = (getattr(client, method)(route, json={"query": "?"}) if method == "post"
                    else client.get(route))
        assert response.status_code == 503
        assert response.json() == {"detail": "service_unavailable"}
        assert "synthetic-private-model-path" not in response.text + caplog.text
    assert model.requests == [] and client.get("/health").status_code == 200


def test_concurrent_searcher_initialization_constructs_only_one_ranker(harness, monkeypatch):
    _, _, ranker, _ = harness
    constructed = []

    def create(path):
        constructed.append(path)
        sleep(.03)
        return ranker

    monkeypatch.setattr(dependencies, "LocalBgeReranker", create)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: dependencies.get_chunk_searcher(), range(4)))
    assert len(constructed) == 1
