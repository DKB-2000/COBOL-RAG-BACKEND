import json

import httpx
import pytest
from fastapi.testclient import TestClient

from legacy_rag.api import dependencies
from legacy_rag.generation.ollama_model import OllamaGenerationModel
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "ollama")
    state = {"requests": [], "code": 200, "done_reason": "stop", "sources": [
        SearchResult("c1", "MOVE 0 TO BALANCE.", "samples/a.cbl", "cobol", "RESET", "h", 0, 0.7),
    ], "answer": {"status": "answered", "reason": None,
                  "claims": [{"text": "초기화한다.", "chunk_ids": ["c1"]}]}}

    def transport(request):
        state["requests"].append(json.loads(request.content))
        if state["code"] == "timeout":
            raise httpx.ReadTimeout("secret-local-code", request=request)
        return httpx.Response(state["code"], json={
            "done": True, "done_reason": state["done_reason"], "message": {
                "role": "assistant", "content": json.dumps(state["answer"]),
                "thinking": "secret-local-code",
            },
        })

    class Searcher:
        def search(self, *, query, limit):
            return state["sources"]

    with httpx.Client(base_url="http://127.0.0.1:11434",
                      transport=httpx.MockTransport(transport)) as client:
        adapter = OllamaGenerationModel(client=client, max_output_tokens=1024)
        app = create_app()
        app.dependency_overrides[dependencies.get_chunk_searcher] = Searcher
        app.dependency_overrides[dependencies.get_generation_model] = lambda: adapter
        with TestClient(app) as api:
            yield api, state


def test_query_returns_validated_claim_and_source(harness):
    api, state = harness
    response = api.post("/query", json={"query": "잔액 초기화?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "초기화한다. [c1]"
    assert response.json()["sources"][0]["chunk_id"] == "c1"
    assert "secret-local-code" not in response.text
    assert len(state["requests"]) == 1


def test_unknown_citation_is_refused(harness):
    api, state = harness
    state["answer"]["claims"][0]["chunk_ids"] = ["unknown"]
    result = api.post("/query", json={"query": "?"}).json()
    assert result["reason"] == "invalid_citations" and result["answer"] is None


def test_empty_context_does_not_call_ollama(harness):
    api, state = harness
    state["sources"] = []
    assert api.post("/query", json={"query": "?"}).json()["reason"] == "no_evidence"
    assert state["requests"] == []


@pytest.mark.parametrize("failure", ["timeout", 500, "length", "malformed"])
def test_failure_is_sanitized_and_search_remains_available(harness, failure):
    api, state = harness
    if failure == "length":
        state["done_reason"] = "length"
    elif failure == "malformed":
        state["answer"] = {"status": "answered", "claims": []}
    else:
        state["code"] = failure
    response = api.post("/query", json={"query": "?"})
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "generation_unavailable"
    assert response.json()["answer"] is None and response.json()["sources"] == []
    assert "secret-local-code" not in response.text
    assert len(state["requests"]) == 1
    assert api.post("/search", json={"query": "?"}).status_code == 200
