import json

import httpx
import pytest

from legacy_rag.generation.models import GeneratedAnswer, GenerationRequest
from legacy_rag.generation.ollama_model import OllamaGenerationModel, create_ollama_model

ANSWER = {"status": "answered", "claims": [{"text": "초기화한다.", "chunk_ids": ["c1"]}],
          "reason": None}


@pytest.fixture
def harness():
    state = {"requests": [], "status": 200, "body": {
        "done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(ANSWER), "thinking": "not the answer",
        },
    }}

    def transport(request):
        state["requests"].append(request)
        if state["status"] == "timeout":
            raise httpx.ReadTimeout("private prompt", request=request)
        return httpx.Response(state["status"], json=state["body"])

    with httpx.Client(base_url="http://127.0.0.1:11434",
                      transport=httpx.MockTransport(transport)) as client:
        yield OllamaGenerationModel(client=client, max_output_tokens=1024), state


def test_structured_answer_uses_local_bounded_request_and_ignores_thinking(harness):
    model, state = harness
    request = GenerationRequest("system", '{"question":"초기화?"}')
    assert model.generate(request) == GeneratedAnswer.model_validate(ANSWER)
    sent = state["requests"][0]
    assert str(sent.url) == "http://127.0.0.1:11434/api/chat"
    body = json.loads(sent.content)
    assert body["model"] == "qwen3:4b"
    assert body["stream"] is False and body["think"] is False
    expected_schema = GeneratedAnswer.model_json_schema()
    expected_schema["required"] = list(expected_schema["properties"])
    assert body["format"] == expected_schema
    assert set(body["format"]["required"]) == {"status", "claims", "reason"}
    assert body["messages"] == [
        {"role": "system", "content": request.system_prompt},
        {"role": "user", "content": request.user_prompt},
    ]
    assert body["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 1024}
    assert body["keep_alive"] == 0


@pytest.mark.parametrize("reason", ["insufficient_evidence", "conflicting_evidence"])
def test_grounding_refusal(harness, reason):
    model, state = harness
    state["body"]["message"]["content"] = json.dumps({"status": "refused", "reason": reason})
    assert model.generate(GenerationRequest("s", "u")).reason == reason


@pytest.mark.parametrize("mutation", ["length", "unfinished", "empty", "json", "contract",
                                      "thinking-only", "tool-role"])
def test_incomplete_or_invalid_output_is_rejected(harness, mutation):
    model, state = harness
    body = state["body"]
    if mutation == "length":
        body["done_reason"] = "length"
    elif mutation == "unfinished":
        body["done"] = False
    elif mutation == "empty":
        body["message"]["content"] = ""
    elif mutation == "json":
        body["message"]["content"] = "```json\n{}\n```"
    elif mutation == "contract":
        body["message"]["content"] = '{"status":"answered","claims":[]}'
    elif mutation == "thinking-only":
        body["message"].pop("content")
        body["message"]["thinking"] = json.dumps(ANSWER)
    else:
        body["message"]["role"] = "tool"
    with pytest.raises(ValueError):
        model.generate(GenerationRequest("s", "u"))


def test_oversized_input_never_reaches_server(harness):
    model, state = harness
    with pytest.raises(ValueError, match="generation input too large"):
        model.generate(GenerationRequest("s", "x" * 16000))
    assert state["requests"] == []


@pytest.mark.parametrize("status", [307, 404, 500, "timeout"])
def test_http_failures_are_not_retried(harness, status):
    model, state = harness
    state["status"] = status
    with pytest.raises(httpx.HTTPError):
        model.generate(GenerationRequest("s", "u"))
    assert len(state["requests"]) == 1


def test_factory_ignores_remote_host_proxy_and_disables_redirects(monkeypatch):
    captured = {}
    original_client = httpx.Client
    monkeypatch.setenv("OLLAMA_HOST", "https://unapproved.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "https://unapproved.invalid")

    def client(**kwargs):
        captured.update(kwargs)
        return original_client(transport=httpx.MockTransport(
            lambda request: httpx.Response(500)), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    model = create_ollama_model(timeout_seconds=300, max_output_tokens=1024)
    try:
        assert captured["base_url"] == "http://127.0.0.1:11434"
        assert captured["trust_env"] is False and captured["follow_redirects"] is False
        assert captured["timeout"].read == 300 and captured["timeout"].connect == 5
    finally:
        model.close()
    assert model._client.is_closed
