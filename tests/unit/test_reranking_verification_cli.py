import json
import runpy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def cli(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "verify_reranking_api.py"))


def test_default_preflight_does_not_start_network_or_server(cli, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify_reranking_api.py"])
    monkeypatch.setattr(cli["httpx"], "Client", lambda **kwargs: pytest.fail("network forbidden"))
    monkeypatch.setattr(cli["subprocess"], "Popen", lambda *a, **k: pytest.fail("server forbidden"))
    cli["main"]()
    assert "generation_calls=0" in capsys.readouterr().out


def test_actual_prompt_must_match_frozen_context_body_order_and_question(cli):
    approved = cli["load_public_chunks"](cli["DATA"])
    chunks = list(approved.values())[:2]
    expected = [chunk.chunk_id for chunk in chunks]
    payload = {"question": "question", "context": [asdict(chunk) for chunk in chunks]}
    case = SimpleNamespace(question="question", id="case")
    assert cli["verify_context"](case, payload, approved, expected) == chunks
    for kind in ("text", "order", "question"):
        changed = json.loads(json.dumps(payload))
        if kind == "text":
            changed["context"][0]["text"] = "private text"
        elif kind == "order":
            changed["context"].reverse()
        else:
            changed["question"] = "different"
        with pytest.raises(ValueError):
            cli["verify_context"](case, changed, approved, expected)
