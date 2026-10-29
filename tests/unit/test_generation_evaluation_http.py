import importlib.util
import io
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from legacy_rag.api.public_corpus import load_public_chunks


@pytest.fixture
def script():
    path = Path(__file__).resolve().parents[2] / "scripts/evaluate_generation.py"
    spec = importlib.util.spec_from_file_location("generation_evaluation_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["normal", "private-text", "timeout"])
def test_probe_respects_budget_and_never_sends_unapproved_context(script, kind):
    approved = load_public_chunks(script.DATA)
    chunk = next(iter(approved.values()))
    requests = []

    def transport(request):
        requests.append(request.url.path)
        if request.url.path == "/search":
            item = {**asdict(chunk), "score": 0.5}
            if kind == "private-text":
                item["text"] = "unapproved private text"
            return httpx.Response(200, json={"results": [item]})
        if kind == "timeout":
            raise httpx.ReadTimeout("private exception details", request=request)
        return httpx.Response(200, json={"status": "refused", "reason": "insufficient_evidence",
                                       "answer": None, "claims": [], "sources": []})

    journal = io.StringIO()
    with httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(transport)) as client:
        probe = script.HttpProbe(client, approved, max_queries=1, journal=journal)
        first = probe("public question")
        second = probe("public question")
    if kind == "private-text":
        assert first["error_kind"] == "search_or_public_corpus_error"
        assert "/query" not in requests
    else:
        assert requests.count("/query") == 1
        assert second["error_kind"] == "query_budget_exhausted"
        assert first["actual_model_prompt_observed"] is False
        assert first["api_query_attempted"] is True
        assert journal.getvalue().count("query_about_to_send") == 1
    if kind == "timeout":
        assert first["error_kind"] == "query_http_timeout_no_retry"
        assert "private exception details" not in str(first)


def test_existing_run_prevents_any_new_http_request(script, tmp_path, monkeypatch):
    monkeypatch.setattr(script, "HERE", tmp_path)
    (tmp_path / "generation-v1-manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["evaluate_generation.py", "--execute"])

    def forbidden(**kwargs):
        pytest.fail("existing run must be rejected before opening an HTTP client")

    monkeypatch.setattr(script.httpx, "Client", forbidden)
    with pytest.raises(FileExistsError):
        script.main()


def test_reranked_preflight_uses_all_candidates_and_frozen_context_policy(script):
    approved = load_public_chunks(script.DATA)
    requests = []

    def transport(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    with httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(transport)) as client:
        assert script.HttpProbe(client, approved, search_limit=30).search("question") == []
    assert requests == [{"query": "question", "limit": 30}]
    original = script.expected_context_ids(approved, "identifier-aware", "disabled")
    reranked = script.expected_context_ids(approved, "identifier-aware", "bge-int8")
    assert len(original) == len(reranked) == 30
    assert original != reranked
    with pytest.raises(ValueError, match="requires identifier-aware"):
        script.expected_context_ids(approved, "original", "bge-int8")
