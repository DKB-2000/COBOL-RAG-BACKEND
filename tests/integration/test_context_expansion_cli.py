import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from legacy_rag.evaluation import run_context_expansion as cli


def test_offline_context_expansion_is_bounded_reproducible_and_preserves_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = Path(__file__).resolve().parents[2] / "data"
    output_path = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv", ["test", "--data-root", str(data_root), "--output-path", str(output_path)]
    )
    cli.main()
    first = output_path.read_bytes()
    output = json.loads(first)
    assert output["reports"]["expanded_top5"]["evaluated_cases"] == 24
    raw = {c["case_id"]: c for c in output["reports"]["raw_top5"]["case_results"]}
    for c in output["reports"]["expanded_top5"]["case_results"]:
        selected = c["retrieved_chunk_ids"]
        seeds = raw[c["case_id"]]["retrieved_chunk_ids"]
        assert selected[:5] == seeds
        assert len(selected) == len(set(selected)) <= 10
        assert c["context_characters"] <= 4000
        assert c["evidence_complete"] >= raw[c["case_id"]]["evidence_complete"]
        for addition in output["expansion_trace"][c["case_id"]]["additions"]:
            assert addition["seed_id"] in seeds
            assert {"target_id": addition["target_id"], "kind": addition["kind"]} in output[
                "relations"
            ][addition["seed_id"]]
    for name in ("budgeted_top10", "expanded_top5"):
        assert output["reports"][name]["metrics"]["max_context_characters"] <= 4000
    for path, digest in output["configuration"]["input_hashes"].items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest
    cli.main()
    assert output_path.read_bytes() == first


def test_context_expansion_rejects_overwriting_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = Path(__file__).resolve().parents[2] / "data"
    baseline_path = data_root / "evaluation/results/multilingual-structured-baseline-v1.json"
    monkeypatch.setattr(sys, "argv", ["test", "--output-path", str(baseline_path)])
    with pytest.raises(ValueError, match="must not overwrite"):
        cli.main()
