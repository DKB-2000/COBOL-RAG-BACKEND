import json
import runpy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from legacy_rag.generation.models import GenerationRequest


@pytest.fixture
def cli(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "evaluate_reranked_generation.py"))


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_preflight_is_offline_without_provider_key(cli, monkeypatch, capsys, provider):
    monkeypatch.setattr("sys.argv", ["evaluate_reranked_generation.py", "--provider", provider])
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("network forbidden"))
    cli["main"]()
    assert "generation_calls=0" in capsys.readouterr().out


def test_resume_never_repeats_an_attempt_even_without_a_response(cli):
    cases, _, _, _ = cli["load_inputs"]()
    calls = [{"question": cases[0].question}]
    assert cli["remaining_cases"](cases, calls) == cases[1:]
    with pytest.raises(ValueError, match="ambiguous"):
        cli["remaining_cases"](cases, calls + calls)
    with pytest.raises(ValueError, match="ambiguous"):
        cli["remaining_cases"](cases, [{"question": "not approved"}])


def test_prompt_gate_and_durable_ledger_precede_paid_sdk_call(cli, monkeypatch, tmp_path):
    import openai

    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("LEGACY_RAG_RERANKING", "bge-int8")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")
    ledger, trace = tmp_path / "calls.jsonl", tmp_path / "trace.jsonl"
    ledger.touch()
    trace.touch()
    monkeypatch.setenv("LEGACY_RAG_EVALUATION_LEDGER", str(ledger))
    monkeypatch.setenv("LEGACY_RAG_EVALUATION_TRACE", str(trace))
    requests = []

    def transport(request):
        # The call intent must already be durable when the SDK sends anything.
        assert len(cli["read_lines"](ledger)) == 1
        requests.append(json.loads(request.content))
        answer = {"status": "refused", "claims": [], "reason": "insufficient_evidence"}
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "status": "completed", "model": "gpt-6-luna", "output": [{
                "id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(answer), "annotations": []}],
            }], "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
        })

    monkeypatch.setattr(openai, "DefaultHttpxClient", lambda **kw: httpx.Client(
        **kw, transport=httpx.MockTransport(transport)))
    _, _, _, expected = cli["load_inputs"]()
    frozen = next(iter(expected.values()))
    request = GenerationRequest(**frozen)
    app = cli["create_evaluation_app"]()
    model = app.dependency_overrides[cli["get_generation_model"]]()
    with TestClient(app):
        bad_payload = json.loads(request.user_prompt)
        bad_payload["context"][0]["text"] = "private text with the same chunk ID"
        with pytest.raises(ValueError, match="differs"):
            model.generate(GenerationRequest(request.system_prompt, json.dumps(bad_payload)))
        assert not requests and not ledger.read_text()
        assert model.generate(request).status == "refused"
        with pytest.raises(ValueError, match="already attempted"):
            model.generate(request)
    assert len(requests) == len(cli["read_lines"](trace)) == 1
    assert requests[0]["model"] == "gpt-6-luna"
    assert requests[0]["store"] is False and requests[0]["max_output_tokens"] == 1000
    assert "secret-test-value" not in trace.read_text(encoding="utf-8")
    assert cli["read_lines"](trace)[0]["provider_response"]["usage"]["total_tokens"] == 7
