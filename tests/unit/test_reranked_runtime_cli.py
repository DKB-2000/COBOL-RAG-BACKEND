import json
import runpy
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def cli(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "verify_reranked_runtime.py"))


@pytest.mark.parametrize("mutate", [False, True])
def test_runtime_uses_search_only_and_detects_context_drift(cli, tmp_path, monkeypatch, mutate):
    cases = cli["load_evaluation_cases"](cli["DATA"] / "evaluation/questions-v1.jsonl")
    approved = cli["load_public_chunks"](cli["DATA"])
    reference = json.loads((cli["DATA"] / "evaluation/results/reranker-int8-length-v1.json")
                           .read_text(encoding="utf-8"))
    ranks = {row["case_id"]: row["ranked_ids"] for row in reference["rankings"]}
    ids = {case.question: case.id for case in cases}
    routes = []

    def transport(request):
        routes.append(request.url.path)
        if request.url.path in {"/health", "/ready"}:
            return httpx.Response(200, json={"status": "ready"})
        assert request.url.path == "/search"
        payload = json.loads(request.content)
        assert payload["limit"] == 30
        ranked = list(ranks[ids[payload["query"]]])
        if mutate and ids[payload["query"]] == "q001":
            ranked[0], ranked[1] = ranked[1], ranked[0]
        return httpx.Response(200, json={"results": [
            {**asdict(approved[key]), "score": .5} for key in ranked]})

    original = httpx.Client
    monkeypatch.setattr(cli["httpx"], "Client", lambda **kw: original(
        **kw, transport=httpx.MockTransport(transport)))
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["verify_reranked_runtime.py", "--output", str(output)])
    if mutate:
        with pytest.raises(RuntimeError, match="differs"):
            cli["main"]()
    else:
        cli["main"]()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["generation_calls"] == report["query_calls"] == 0
    assert report["context_matches"] == (29 if mutate else 30)
    assert report["evidence_count"] == 22
    assert len([route for route in routes if route == "/search"]) == 30
    assert "/query" not in routes


def test_existing_output_blocks_network(cli, tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    output.write_text("preserved", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["verify_reranked_runtime.py", "--output", str(output)])
    monkeypatch.setattr(cli["httpx"], "Client", lambda **kw: pytest.fail("network forbidden"))
    with pytest.raises(FileExistsError):
        cli["main"]()
    assert output.read_text(encoding="utf-8") == "preserved"
