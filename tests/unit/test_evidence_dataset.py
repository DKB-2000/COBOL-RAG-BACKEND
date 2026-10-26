import json
from pathlib import Path

import pytest

from legacy_rag.evaluation.dataset import EvaluationCase, load_evaluation_cases
from legacy_rag.evaluation.evidence import contains_code, load_evidence_requirements
from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_files


def test_fixed_evidence_annotations_cover_all_answerable_cases_and_real_chunks() -> None:
    data_root = Path(__file__).resolve().parents[2] / "data"
    cases = load_evaluation_cases(data_root / "evaluation" / "questions-v1.jsonl")
    requirements = load_evidence_requirements(
        data_root / "evaluation" / "evidence-v1.jsonl",
        cases=cases,
        data_root=data_root,
    )
    chunks = [
        chunk
        for doc in load_cobol_files((data_root / "samples").glob("*.cbl"), data_root=data_root)
        for chunk in chunk_cobol_structure(doc)
    ]

    assert len(requirements) == 24
    assert all(
        any(
            chunk.source_path == unit.source_path
            and all(contains_code(chunk.text, anchor) for anchor in unit.anchors)
            for chunk in chunks
        )
        for units in requirements.values()
        for unit in units
    )


@pytest.mark.parametrize("problem", ["missing", "duplicate", "wrong-anchor", "wrong-source"])
def test_invalid_annotations_fail_instead_of_reducing_denominator(
    tmp_path: Path, problem: str
) -> None:
    (tmp_path / "a.cbl").write_text("OPEN INPUT DATA-IN.", encoding="utf-8")
    case = EvaluationCase("q1", "open?", ("a.cbl",), ("DATA-IN",), True, ())
    record = {
        "case_id": "q1",
        "required_evidence": [{"source_path": "a.cbl", "anchors": ["OPEN INPUT DATA-IN"]}],
    }
    if problem == "wrong-anchor":
        record["required_evidence"][0]["anchors"] = ["READ OTHER-FILE"]
    if problem == "wrong-source":
        record["required_evidence"][0]["source_path"] = "b.cbl"
    text = json.dumps(record) + "\n"
    if problem == "missing":
        text = ""
    if problem == "duplicate":
        text += text
    path = tmp_path / "evidence.jsonl"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError):
        load_evidence_requirements(path, cases=[case], data_root=tmp_path)
