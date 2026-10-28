import io
import json
import runpy
import sys
from pathlib import Path

import pytest


def load_cli():
    path = Path(__file__).resolve().parents[2] / "scripts/verify_runtime.py"
    return runpy.run_path(str(path))


def test_runtime_verification_only_indexes_public_five_and_never_calls_generation(tmp_path, monkeypatch):
    cli = load_cli()
    calls = []

    class Opener:
        text = "public source body"

        def open(self, request, **kwargs):
            route = request.full_url.split(":8001")[1]
            calls.append((route, json.loads(request.data) if request.data else None))
            responses = {
                "/health": {"status": "ok"}, "/ready": {"status": "ready"},
                "/documents/index": {"indexed_documents": 5, "indexed_chunks": 52},
                "/search": {"results": [{"chunk_id": "id", "text": self.text,
                                         "source_path": "samples/account-balance.cbl",
                                         "language": "cobol", "symbol": "A", "chunk_index": 0}]},
            }
            return io.BytesIO(json.dumps(responses[route]).encode())

    opener = Opener()
    cli["main"].__globals__["build_opener"] = lambda *args: opener
    before = tmp_path / "before.json"
    monkeypatch.setattr(sys, "argv", ["verify_runtime.py", "--index", "--output", str(before)])
    cli["main"]()
    report = json.loads(before.read_text())
    assert report["n"] == 10 and report["generation_calls"] == 0
    assert len([route for route, _ in calls if route == "/search"]) == 11
    index_calls = [payload for route, payload in calls if route == "/documents/index"]
    assert len(index_calls) == 1 and index_calls[0]["rebuild"] is False
    assert set(index_calls[0]["source_paths"]) == set(cli["PUBLIC_SOURCE_HASHES"])
    assert all(route != "/query" for route, _ in calls)

    after = tmp_path / "after.json"
    monkeypatch.setattr(sys, "argv", ["verify_runtime.py", "--compare", str(before), "--output", str(after)])
    cli["main"]()
    assert json.loads(after.read_text())["comparison_matches"] is True
    assert len([route for route, _ in calls if route == "/documents/index"]) == 1

    mismatch = tmp_path / "mismatch.json"
    opener.text = "different source body"
    monkeypatch.setattr(sys, "argv", ["verify_runtime.py", "--compare", str(before), "--output", str(mismatch)])
    with pytest.raises(RuntimeError, match="Persistence comparison failed"):
        cli["main"]()
    assert json.loads(mismatch.read_text())["comparison_matches"] is False


def test_runtime_verification_rejects_existing_output_before_any_network(tmp_path, monkeypatch):
    cli = load_cli()
    output = tmp_path / "existing.json"
    output.write_text("preserve")
    cli["main"].__globals__["build_opener"] = lambda *args: pytest.fail("network must not start")
    monkeypatch.setattr(sys, "argv", ["verify_runtime.py", "--index", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        cli["main"]()
    assert error.value.code == 2
    assert output.read_text() == "preserve"
