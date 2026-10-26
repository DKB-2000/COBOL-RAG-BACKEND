import pytest
from fastapi.testclient import TestClient

from legacy_rag.api.dependencies import get_chunk_searcher, get_generation_model
from legacy_rag.generation.models import AnswerClaim, GeneratedAnswer
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult


class Searcher:
    def search(self, *, query, limit):
        return [SearchResult("c1", "MOVE 0 TO BALANCE.", "samples/a.cbl", "cobol", "RESET", "h", 0, 0.7)]


class Model:
    def generate(self, request):
        return GeneratedAnswer(status="answered", claims=[AnswerClaim(text="초기화한다.", chunk_ids=["c1"])])


def client_for(model):
    app = create_app()
    app.dependency_overrides[get_chunk_searcher] = Searcher
    app.dependency_overrides[get_generation_model] = lambda: model
    return TestClient(app)


def test_query_api_returns_claims_and_source_metadata():
    response = client_for(Model()).post("/query", json={"query": "초기화?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered" and payload["reason"] is None
    assert payload["answer"] == "초기화한다. [c1]"
    assert payload["claims"] == [{"text": "초기화한다.", "chunk_ids": ["c1"]}]
    assert payload["sources"] == [{
        "chunk_id": "c1", "source_path": "samples/a.cbl", "language": "cobol",
        "symbol": "RESET", "chunk_index": 0, "score": 0.7,
    }]


def test_default_model_is_disabled_and_search_still_works():
    client = client_for(None)
    payload = client.post("/query", json={"query": "?"}).json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "generation_unavailable"
    assert payload["answer"] is None and payload["sources"] == []
    assert client.post("/search", json={"query": "?"}).status_code == 200


def test_model_exception_does_not_leak_secret_or_disable_search():
    class BrokenModel:
        def generate(self, request):
            raise RuntimeError("secret-api-key")

    client = client_for(BrokenModel())
    response = client.post("/query", json={"query": "?"})
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert "secret-api-key" not in response.text
    assert client.post("/search", json={"query": "?"}).status_code == 200


def test_empty_search_does_not_call_model_at_http_boundary():
    class EmptySearcher:
        def search(self, *, query, limit):
            return []

    class MustNotRun:
        def generate(self, request):
            pytest.fail("model must not run without context")

    client = client_for(MustNotRun())
    client.app.dependency_overrides[get_chunk_searcher] = EmptySearcher
    response = client.post("/query", json={"query": "?"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "refused", "reason": "no_evidence", "answer": None,
        "claims": [], "sources": [],
    }


@pytest.mark.parametrize("reason", ["insufficient_evidence", "conflicting_evidence"])
def test_model_refusal_is_exposed_without_answer_or_sources(reason):
    class RefusingModel:
        def generate(self, request):
            return GeneratedAnswer(status="refused", reason=reason)

    response = client_for(RefusingModel()).post("/query", json={"query": "?"})
    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert response.json()["reason"] == reason
    assert response.json()["answer"] is None and response.json()["sources"] == []


@pytest.mark.parametrize("payload", [{"query": ""}, {"query": "  "}, {"query": "?", "limit": 0}, {"query": "?", "limit": 11}])
def test_query_rejects_invalid_input(payload):
    assert client_for(Model()).post("/query", json=payload).status_code == 422


def test_query_openapi_exposes_request_response_contract():
    schema = create_app().openapi()
    operation = schema["paths"]["/query"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/QueryRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/QueryResponse"
    }
