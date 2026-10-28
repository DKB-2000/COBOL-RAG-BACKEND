from dataclasses import replace

import pytest

from legacy_rag.evaluation.dataset import EvaluationCase
from legacy_rag.evaluation.generation_runner import collect_generation, make_review_template


def case(index=1, *, answerable=True):
    return EvaluationCase(
        f"q{index:03}", f"question {index}", ("samples/test.cbl",), ("EXPECTED-SYMBOL",),
        answerable, (),
    )


def response(status="refused", reason="insufficient_evidence"):
    return {"response": {"status": status, "reason": reason, "answer": None,
                         "claims": [], "sources": []}, "api_query_attempted": True}


def test_collects_all_24_answerable_and_six_unanswerable_without_ground_truth_leakage():
    cases = [case(i, answerable=i <= 24) for i in range(1, 31)]
    sent = []
    saved = []

    def query(question):
        sent.append(question)
        return response()

    records = collect_generation(cases, query, on_result=saved.append)
    assert len(records) == len(saved) == 30
    assert sum(r["answerable"] for r in records) == 24
    assert sent == [c.question for c in cases]
    assert all("EXPECTED-SYMBOL" not in text for text in sent)


@pytest.mark.parametrize("outcome", ["raise", "bad-contract", "http-timeout", "not-an-object"])
def test_failed_case_is_preserved_and_next_case_still_runs_without_secret_leak(outcome):
    calls = []

    def query(question):
        calls.append(question)
        if len(calls) == 1:
            if outcome == "raise":
                raise RuntimeError("private-provider-error-token")
            if outcome == "bad-contract":
                return {"response": {"status": "unexpected"}}
            if outcome == "http-timeout":
                return {"error_kind": "query_http_timeout_no_retry", "api_query_attempted": True}
            return None
        return response()

    records = collect_generation([case(), case(2)], query)
    assert [r["status"] for r in records] == ["error", "refused"]
    assert len(calls) == 2
    assert "private-provider-error-token" not in str(records)


def test_duplicate_ids_are_rejected_before_any_query():
    def forbidden(question):
        pytest.fail("must validate IDs before querying")

    with pytest.raises(ValueError, match="duplicate"):
        collect_generation([case(), replace(case(), question="different")], forbidden)


def test_review_template_keeps_semantic_scores_pending():
    records = collect_generation([case()], lambda question: response())
    review = make_review_template(records, {"q001": ["required answer"]})[0]
    assert review["answer_correct"] is review["answer_complete"] is None
    assert review["reviewer"] is None and review["atomic_facts"] == []
