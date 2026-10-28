import pytest

from legacy_rag.evaluation.answer_metrics import summarize_generation


def record(case_id="a", *, answerable=True, status="answered", reason=None):
    claims = [{"text": "balance fact", "chunk_ids": ["valid-id"]}] if status == "answered" else []
    sources = [{"chunk_id": "valid-id"}] if claims else []
    return {"case_id": case_id, "answerable": answerable, "status": status,
            "response": {"claims": claims, "sources": sources, "reason": reason},
            "query_elapsed_seconds": 2.0, "api_query_attempted": True}


def review(case_id="a", *, correct=True, complete=True, grounding="supported", citation="supported"):
    return {"case_id": case_id, "rubric_version": "answer-rubric-v1",
            "reviewer": "test-reviewer", "reviewer_kind": "human",
            "answer_correct": correct, "answer_complete": complete, "refusal_correct": None,
            "atomic_facts": [{"claim_index": 0, "text": "one factual statement",
                              "grounding": grounding, "citation_support": citation}]}


def test_valid_citation_id_does_not_make_a_false_claim_semantically_correct():
    summary = summarize_generation([record()], [review(correct=False, grounding="contradicted")])
    assert summary["citation_id_linkage"]["rate"] == 1
    assert summary["answer_correct"]["rate"] == 0
    assert summary["grounded_complete_answer"]["rate"] == 0
    assert summary["semantic_grounding"]["rate"] == 0


def test_correct_but_incomplete_or_poorly_cited_answer_is_not_grounded_success():
    for annotation in [review(complete=False), review(citation="insufficient")]:
        summary = summarize_generation([record()], [annotation])
        assert summary["answer_correct"]["rate"] == 1
        assert summary["grounded_complete_answer"]["rate"] == 0


def test_missing_or_partial_reviews_are_not_reported_as_measured_accuracy():
    summary = summarize_generation([record()])
    assert summary["answer_correct"]["rate"] is None
    assert summary["answer_correct"]["pending"] == 1
    assert summary["grounded_complete_answer"]["rate"] is None
    partial = review(grounding="pending")
    assert summarize_generation([record()], [partial])["grounded_complete_answer"]["rate"] is None


def test_refusal_denominator_includes_unavailable_error_and_invalid_citations():
    records = [record(str(i), answerable=False, status=status, reason=reason)
               for i, (status, reason) in enumerate([
                   ("refused", "insufficient_evidence"), ("refused", "invalid_citations"),
                   ("unavailable", "generation_unavailable"), ("error", None),
                   ("answered", None), ("refused", "conflicting_evidence"),
               ])]
    annotation = {"case_id": "0", "rubric_version": "answer-rubric-v1",
                  "reviewer": "test-reviewer", "reviewer_kind": "human", "refusal_correct": True}
    summary = summarize_generation(records, [annotation])
    assert summary["correct_refusal"] == {"passed": 1, "denominator": 6, "pending": 0, "rate": 1 / 6}


def test_empty_claims_are_na_and_split_facts_can_have_different_support():
    empty = summarize_generation([record(status="refused", reason="no_evidence")])
    assert empty["semantic_grounding"]["rate"] is None
    assert empty["citation_id_linkage"]["rate"] is None
    annotation = review()
    annotation["atomic_facts"].append({"claim_index": 0, "text": "second fact",
                                        "grounding": "insufficient", "citation_support": "insufficient"})
    summary = summarize_generation([record()], [annotation])
    assert summary["semantic_grounding"]["denominator"] == 2
    assert summary["semantic_grounding"]["rate"] == 0.5


def test_reviewer_provenance_is_required_and_codex_is_not_labelled_human():
    annotation = review()
    annotation["reviewer"] = None
    with pytest.raises(ValueError, match="attribution"):
        summarize_generation([record()], [annotation])
    annotation.update(reviewer="codex", reviewer_kind="codex_orchestrator")
    assert summarize_generation([record()], [annotation])["reviewer_kinds"] == {"codex_orchestrator": 1}


def test_unknown_duplicate_reviews_and_out_of_range_claim_indices_are_rejected():
    for annotations in [[review("unknown")], [review(), review()]]:
        with pytest.raises(ValueError):
            summarize_generation([record()], annotations)
    annotation = review()
    annotation["atomic_facts"][0]["claim_index"] = 2
    with pytest.raises(ValueError, match="atomic"):
        summarize_generation([record()], [annotation])
