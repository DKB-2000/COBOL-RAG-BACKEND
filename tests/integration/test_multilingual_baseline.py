import json
import sys
from pathlib import Path

import pytest

from legacy_rag.evaluation import run_multilingual_baseline as cli
from legacy_rag.evaluation.multilingual_embedding import MODEL_FILES, MODEL_ID, MODEL_REVISION


@pytest.mark.parametrize("windowed", [False, True])
def test_multilingual_cli_preserves_inputs_and_reports_evidence_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windowed: bool,
) -> None:
    data_root = Path(__file__).resolve().parents[2] / "data"
    baseline_name = (
        "multilingual-structured-baseline-v1.json"
        if windowed
        else "contextual-structured-baseline-v1.json"
    )
    baseline_path = data_root / "evaluation/results" / baseline_name
    baseline_hash = cli.file_hash(baseline_path)
    for name in MODEL_FILES:
        path = tmp_path / "model" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model-test-fixture")
    calls = []

    def download(model_id, **kwargs):
        assert model_id == MODEL_ID
        assert kwargs["revision"] == MODEL_REVISION
        assert kwargs["token"] is False
        assert kwargs["local_files_only"] is True
        return str(tmp_path / "model")

    class FakeEncoder:
        max_length = 128
        overlap = 32

        def __init__(self, model_dir):
            assert model_dir == tmp_path / "model"

        def token_lengths(self, texts):
            return [200 if len(text) > 400 else 10 for text in texts]

        def __call__(self, texts):
            calls.append(texts)
            return [[1.0, 0.0] for _ in texts]

        def window_statistics(self, texts):
            return [
                {"window_count": 2 if len(text) > 400 else 1, "complete": True} for text in texts
            ]

    monkeypatch.setattr(cli, "snapshot_download", download)
    monkeypatch.setattr(cli, "MultilingualOnnxEmbedding", FakeEncoder)
    monkeypatch.setattr(cli, "WindowedMultilingualOnnxEmbedding", FakeEncoder)
    output_path = tmp_path / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "test",
            "--data-root",
            str(data_root),
            "--chroma-path",
            str(tmp_path / "chroma"),
            "--output-path",
            str(output_path),
            "--local-files-only",
        ]
        + (["--windowed"] if windowed else []),
    )

    cli.main()

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["chunk_count"] == 52
    assert output["configuration"]["revision"] == MODEL_REVISION
    assert output["baseline_evidence"]["evaluated_cases"] == 24
    assert output["multilingual_evidence"]["evaluated_cases"] == 24
    assert len(output["retrieved_chunks_by_case_id"]) == 24
    assert all(len(chunks) == 10 for chunks in output["retrieved_chunks_by_case_id"].values())
    lengths = output["input_lengths"] if windowed else output["truncation"]
    assert len(lengths["document_token_lengths"]) == 52
    assert len(lengths["query_token_lengths"]) == 24
    if windowed:
        assert output["windowing"]["document_windows"] > 52
        assert output["windowing"]["query_windows"] == 24
        assert output["windowing"]["overlap"] == 32
        assert all(item["complete"] for item in output["windowing"]["documents"].values())
    assert len(calls[0]) == 52
    assert all(text.startswith("Source path: samples/") for text in calls[0])
    assert len(calls[1:]) == 24
    assert all(len(texts) == 1 for texts in calls[1:])
    assert cli.file_hash(baseline_path) == baseline_hash


def test_multilingual_cli_rejects_overwriting_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = Path(__file__).resolve().parents[2] / "data"
    baseline_path = data_root / "evaluation/results/contextual-structured-baseline-v1.json"
    monkeypatch.setattr(sys, "argv", ["test", "--output-path", str(baseline_path)])
    with pytest.raises(ValueError, match="must not overwrite"):
        cli.main()
