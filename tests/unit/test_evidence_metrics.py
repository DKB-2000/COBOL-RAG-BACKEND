import pytest

from legacy_rag.evaluation.dataset import EvaluationCase
from legacy_rag.evaluation.evidence import (
    EvidenceChunk,
    EvidenceRequirement,
    contains_code,
    evaluate_chunk_evidence,
)


def test_evidence_requires_implementation_not_just_paragraph_reference() -> None:
    case = EvaluationCase("q1", "open file?", ("a.cbl",), ("OPEN-FILES",), True, ())
    unit = EvidenceRequirement("a.cbl", ("OPEN-FILES.", "OPEN INPUT CUSTOMER-IN"))
    rankings = [
        EvidenceChunk("reference", "a.cbl", "MAIN. PERFORM OPEN-FILES."),
        EvidenceChunk("wrong-source", "b.cbl", "OPEN-FILES. OPEN INPUT CUSTOMER-IN."),
        EvidenceChunk("implementation", "a.cbl", "OPEN-FILES.\n  OPEN INPUT CUSTOMER-IN."),
    ]

    report = evaluate_chunk_evidence([case], {"q1": (unit,)}, {"q1": rankings}, ks=(1, 2, 3))

    assert report["metrics"]["1"]["symbol_coverage"] == 1.0
    assert report["metrics"]["2"]["evidence_complete"] == 0.0
    assert report["metrics"]["3"]["evidence_complete"] == 1.0


def test_evidence_requires_all_units_and_excludes_unanswerable_cases() -> None:
    case = EvaluationCase("q1", "open and read?", ("a.cbl",), ("OPEN-FILES", "READ-ITEM"), True, ())
    refused = EvaluationCase("q2", "missing?", (), (), False, ())
    units = (
        EvidenceRequirement("a.cbl", ("OPEN INPUT DATA-IN",)),
        EvidenceRequirement("a.cbl", ("READ DATA-IN",)),
    )
    ranks = [
        EvidenceChunk("open", "a.cbl", "OPEN-FILES. OPEN INPUT DATA-IN."),
        EvidenceChunk("read", "a.cbl", "READ-ITEM. READ DATA-IN."),
    ]

    report = evaluate_chunk_evidence([case, refused], {"q1": units}, {"q1": ranks}, ks=(1, 2))

    assert report["evaluated_cases"] == 1
    assert report["metrics"]["1"]["evidence_hit"] == 1.0
    assert report["metrics"]["1"]["evidence_coverage"] == 0.5
    assert report["metrics"]["1"]["evidence_complete"] == 0.0
    assert report["metrics"]["2"]["evidence_complete"] == 1.0
    assert report["metrics"]["2"]["context_characters"] == sum(len(c.text) for c in ranks)


def test_anchors_must_occur_together_in_one_chunk() -> None:
    case = EvaluationCase("q1", "open?", ("a.cbl",), ("OPEN-FILES",), True, ())
    ranks = [
        EvidenceChunk("label", "a.cbl", "OPEN-FILES."),
        EvidenceChunk("body", "a.cbl", "OPEN INPUT DATA-IN."),
    ]
    unit = EvidenceRequirement("a.cbl", ("OPEN-FILES.", "OPEN INPUT DATA-IN"))

    report = evaluate_chunk_evidence([case], {"q1": (unit,)}, {"q1": ranks}, ks=(2,))

    assert report["metrics"]["2"]["evidence_complete"] == 0.0


def test_code_matching_respects_identifier_boundaries_and_whitespace() -> None:
    assert not contains_code("WS-INDEX-OTHER WS-END-OF-FILE", "WS-INDEX")
    assert not contains_code("WS-END-OF-FILE", "END-OF-FILE")
    assert contains_code("05 item\n  OCCURS   20 TIMES.", "OCCURS 20 TIMES")
    with pytest.raises(ValueError, match="empty"):
        contains_code("text", "  ")


def test_missing_rankings_do_not_silently_reduce_evaluation_denominator() -> None:
    case = EvaluationCase("q1", "open?", ("a.cbl",), ("OPEN-FILES",), True, ())
    with pytest.raises(KeyError):
        evaluate_chunk_evidence(
            [case],
            {"q1": (EvidenceRequirement("a.cbl", ("OPEN INPUT DATA-IN",)),)},
            {},
        )
