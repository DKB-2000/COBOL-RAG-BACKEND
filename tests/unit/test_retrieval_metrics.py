from legacy_rag.evaluation.dataset import EvaluationCase
from legacy_rag.evaluation.metrics import (
    hit_at_k,
    reciprocal_rank,
    summarize_rankings,
)


def test_retrieval_metrics_use_first_relevant_source_rank() -> None:
    retrieved_sources = [
        "samples/other.cbl",
        "samples/target.cbl",
        "samples/third.cbl",
    ]
    expected_sources = {"samples/target.cbl"}

    assert (
        hit_at_k(
            retrieved_sources,
            expected_sources,
            k=1,
        )
        == 0.0
    )
    assert (
        hit_at_k(
            retrieved_sources,
            expected_sources,
            k=2,
        )
        == 1.0
    )
    assert (
        reciprocal_rank(
            retrieved_sources,
            expected_sources,
        )
        == 0.5
    )


def test_retrieval_metrics_return_zero_when_source_is_missing() -> None:
    retrieved_sources = [
        "samples/other.cbl",
        "samples/third.cbl",
    ]
    expected_sources = {"samples/target.cbl"}

    assert (
        hit_at_k(
            retrieved_sources,
            expected_sources,
            k=5,
        )
        == 0.0
    )
    assert (
        reciprocal_rank(
            retrieved_sources,
            expected_sources,
        )
        == 0.0
    )


def test_summarize_rankings_uses_only_answerable_cases() -> None:
    cases = [
        EvaluationCase(
            id="q001",
            question="first",
            expected_sources=("samples/first.cbl",),
            expected_symbols=(),
            answerable=True,
            tags=(),
        ),
        EvaluationCase(
            id="q002",
            question="second",
            expected_sources=("samples/second.cbl",),
            expected_symbols=(),
            answerable=True,
            tags=(),
        ),
        EvaluationCase(
            id="q003",
            question="unanswerable",
            expected_sources=(),
            expected_symbols=(),
            answerable=False,
            tags=("unanswerable",),
        ),
    ]
    rankings_by_case_id = {
        "q001": [
            "samples/first.cbl",
            "samples/other.cbl",
        ],
        "q002": [
            "samples/other.cbl",
            "samples/second.cbl",
        ],
        "q003": [],
    }

    summary = summarize_rankings(
        cases,
        rankings_by_case_id,
        k=2,
    )

    assert summary.evaluated_cases == 2
    assert summary.hit_at_k == 1.0
    assert summary.mrr == 0.75
