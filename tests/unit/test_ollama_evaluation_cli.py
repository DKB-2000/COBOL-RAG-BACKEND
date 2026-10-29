import runpy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from legacy_rag.retrieval.chroma_store import SearchResult


@pytest.fixture
def cli(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "evaluate_ollama.py"))


def test_default_preflight_never_opens_network(cli, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("preflight must not open a network client")

    monkeypatch.setattr(cli["httpx"], "Client", forbidden)
    monkeypatch.setattr(cli["sys"], "argv", ["evaluate_ollama.py"])
    cli["main"]()
    assert "generation_calls=0" in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["question", "hash", "duplicate"])
def test_reference_mutations_block_evaluation(cli, tmp_path, mutation):
    (tmp_path / "input.txt").write_bytes(b"original")
    cases = [SimpleNamespace(id=f"q{i}", question=f"question {i}", answerable=i < 24)
             for i in range(30)]
    rows = [{"case_id": case.id, "question": case.question} for case in cases]
    baseline = {"input_hashes": {"input.txt": sha256(b"original").hexdigest()},
                "system_prompt_sha256": sha256(cli["SYSTEM_PROMPT"].encode()).hexdigest()}
    if mutation == "question":
        rows[0]["question"] = "changed"
    elif mutation == "hash":
        (tmp_path / "input.txt").write_bytes(b"changed")
    else:
        rows[-1] = rows[0]
    with pytest.raises(ValueError):
        cli["validate_reference"](cases, rows, baseline, project=tmp_path)


def test_context_text_mismatch_is_rejected_even_if_chunk_id_is_unchanged(cli):
    source = SearchResult("id", "original code", "samples/a.cbl", "cobol", "A", "h", 0, 0.5)
    reference = {"reconstructed_context": [{key: getattr(source, key) for key in
                                           ("chunk_id", "text", "source_path", "symbol")}]}
    cli["verify_context"](SimpleNamespace(id="q001"), [source], reference)
    with pytest.raises(ValueError, match="baseline context differs"):
        cli["verify_context"](SimpleNamespace(id="q001"),
                              [replace(source, text="different code")], reference)


def test_resume_excludes_completed_errors_too_and_keeps_order(cli):
    cases = [SimpleNamespace(id=f"q{i:03}", question=f"question{i}", answerable=i < 25)
             for i in range(1, 31)]
    completed = [{"case_id": case.id, "question": case.question, "answerable": case.answerable,
                  "status": "error" if case.id == "q002" else "answered"} for case in cases[:11]]
    assert [case.id for case in cli["pending_cases"](cases, completed)] == [
        case.id for case in cases[11:]]
    assert len(completed) == 11


@pytest.mark.parametrize("mutation", ["duplicate", "question", "unknown"])
def test_resume_rejects_ambiguous_history(cli, mutation):
    case = SimpleNamespace(id="q001", question="question", answerable=True)
    rows = [{"case_id": case.id, "question": case.question, "answerable": case.answerable}]
    if mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "question":
        rows[0]["question"] = "different"
    else:
        rows[0]["case_id"] = "q999"
    with pytest.raises(ValueError):
        cli["pending_cases"]([case], rows)


def test_explicit_environmental_subset_does_not_run_other_cases(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli["sys"], "argv", ["evaluate_ollama.py", "--case-id", "q002",
                                            "--case-id", "q018"])
    cli["main"]()
    assert "selected=2" in capsys.readouterr().out


@pytest.mark.parametrize("ids", [("q002", "q002"), ("q999",)])
def test_explicit_subset_rejects_duplicate_or_unknown_ids(cli, monkeypatch, ids):
    argv = ["evaluate_ollama.py"]
    for case_id in ids:
        argv.extend(["--case-id", case_id])
    monkeypatch.setattr(cli["sys"], "argv", argv)
    with pytest.raises(ValueError, match="unknown case ID"):
        cli["main"]()
