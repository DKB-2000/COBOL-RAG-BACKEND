"""Offline HTTP contract tests with the real SDK and an in-memory transport."""
import json
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from legacy_rag.api import dependencies
from legacy_rag.api.public_corpus import load_public_chunks
from legacy_rag.generation.models import GenerationRequest
from legacy_rag.generation.openai_model import OpenAIGenerationModel, create_openai_model
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult

openai = pytest.importorskip("openai", reason="install .[dev,openai] to test the SDK wire contract")


@pytest.fixture
def harness(monkeypatch):
    data_root = Path(__file__).resolve().parents[2] / "data"
    monkeypatch.setenv("LEGACY_RAG_DATA_ROOT", str(data_root))
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    chunk = next(c for c in load_public_chunks(data_root).values() if len(c.text) < 4000)
    state = {"sources": [SearchResult(**asdict(chunk), score=0.5)], "requests": [], "code": 200}
    state["answer"] = {
        "status": "answered", "claims": [{"text": "공개 코드 설명", "chunk_ids": [chunk.chunk_id]}],
        "reason": None,
    }

    def transport(request):
        state["requests"].append(json.loads(request.content))
        assert request.url == "https://api.openai.com/v1/responses"
        if state["code"] == "timeout":
            raise httpx.ReadTimeout("test-only-secret in timeout", request=request)
        if state["code"] != 200:
            return httpx.Response(state["code"], json={"error": {"message": "test-only-secret"}})
        output = state.get("output", [{
            "type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(state["answer"]),
                         "annotations": []}],
        }])
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 1,
            "model": "gpt-6-luna", "status": state.get("status", "completed"),
            "output": output,
            "incomplete_details": {"reason": "max_output_tokens"}
            if state.get("status") == "incomplete" else None,
        })

    with openai.OpenAI(
        api_key="not-a-real-key", max_retries=0, timeout=1,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as sdk:
        adapter = OpenAIGenerationModel(client=sdk, model="gpt-6-luna", max_output_tokens=1000)

        class Searcher:
            def search(self, *, query, limit):
                return state["sources"]

        app = create_app()
        app.dependency_overrides[dependencies.get_chunk_searcher] = Searcher
        app.dependency_overrides[dependencies.get_generation_model] = lambda: adapter
        with TestClient(app) as client:
            yield client, state


def test_real_sdk_http_query_returns_validated_citations_and_strict_schema(harness):
    client, state = harness
    response = client.post("/query", json={"query": "코드 설명?"})
    assert response.status_code == 200 and response.json()["status"] == "answered"
    assert response.json()["sources"][0]["chunk_id"] == state["sources"][0].chunk_id
    request = state["requests"][0]
    assert request["store"] is False and request["max_output_tokens"] == 1000
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert set(request["text"]["format"]["schema"]["required"]) == {"status", "claims", "reason"}


def test_client_factory_fixes_endpoint_and_disables_retries_and_environment_proxy(monkeypatch):
    captured = {"requests": []}
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unapproved.invalid/v1")

    def transport(request):
        captured["requests"].append(request)
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    def http_client(**kwargs):
        captured.update(kwargs)
        return httpx.Client(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(openai, "DefaultHttpxClient", http_client)
    adapter = create_openai_model(
        api_key="not-a-real-key", model="gpt-6-luna", timeout_seconds=12, max_output_tokens=1000,
    )
    try:
        with pytest.raises(openai.RateLimitError):
            adapter.generate(GenerationRequest("system", "public test"))
        assert len(captured["requests"]) == 1
        request = captured["requests"][0]
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.extensions["timeout"]["read"] == 12
        assert request.extensions["timeout"]["connect"] == 5
        assert captured["trust_env"] is False
    finally:
        adapter.close()


@pytest.mark.parametrize("code", [401, 429, 500, "timeout"])
def test_provider_failure_is_sanitized_without_retry_or_disabling_search(harness, code):
    client, state = harness
    state["code"] = code
    response = client.post("/query", json={"query": "설명?"})
    assert response.status_code == 200 and response.json()["status"] == "unavailable"
    assert "test-only-secret" not in response.text
    assert len(state["requests"]) == 1
    assert client.post("/search", json={"query": "설명?"}).status_code == 200


@pytest.mark.parametrize("mutation", ["path", "text", "empty"])
def test_private_tampered_or_empty_context_never_reaches_provider(harness, mutation):
    client, state = harness
    if mutation == "path":
        state["sources"] = [replace(state["sources"][0], source_path="raw/private.cbl")]
    elif mutation == "text":
        state["sources"] = [replace(state["sources"][0], text="private body with public metadata")]
    else:
        state["sources"] = []
    response = client.post("/query", json={"query": "설명?"})
    assert response.json()["status"] == "refused"
    assert response.json()["reason"] == "no_evidence"
    assert state["requests"] == []


def test_mixed_search_results_send_only_approved_context(harness):
    client, state = harness
    public = state["sources"][0]
    state["sources"].insert(0, replace(
        public, chunk_id="private", source_path="raw/private.cbl", text="PRIVATE-LOCAL-ONLY",
    ))
    response = client.post("/query", json={"query": "공개 코드 설명?"})
    assert response.json()["status"] == "answered"
    assert "PRIVATE-LOCAL-ONLY" not in json.dumps(state["requests"])


def test_sdk_grounding_refusal_is_returned(harness):
    client, state = harness
    state["answer"] = {"status": "refused", "claims": [], "reason": "insufficient_evidence"}
    assert client.post("/query", json={"query": "없는 기능?"}).json()["reason"] == "insufficient_evidence"


def test_sdk_cannot_cite_unknown_chunk(harness):
    client, state = harness
    state["answer"]["claims"][0]["chunk_ids"] = ["unknown"]
    assert client.post("/query", json={"query": "설명?"}).json()["reason"] == "invalid_citations"


@pytest.mark.parametrize("variant", ["truncated", "malformed", "safety-refusal"])
def test_non_answer_provider_outputs_fail_closed(harness, variant):
    client, state = harness
    if variant == "truncated":
        state["status"] = "incomplete"
    elif variant == "malformed":
        state["answer"] = {"status": "answered", "claims": [], "reason": None}
    else:
        state["output"] = [{
            "type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
            "content": [{"type": "refusal", "refusal": "test-only-secret"}],
        }]
    response = client.post("/query", json={"query": "설명?"})
    assert response.json()["status"] == "unavailable"
    assert response.json()["answer"] is None and response.json()["sources"] == []
    assert "test-only-secret" not in response.text


def test_oversized_question_is_rejected_before_any_provider_call(harness):
    client, state = harness
    assert client.post("/query", json={"query": "x" * 4001}).status_code == 422
    assert state["requests"] == []
