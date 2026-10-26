from legacy_rag.evaluation.dataset import EvaluationCase
from legacy_rag.evaluation.runner import evaluate_retrieval


def test_evaluate_retrieval_queries_only_answerable_cases() -> None:
    cases = [
        EvaluationCase(
            id="q001",
            question="first question",
            expected_sources=("samples/first.cbl",),
            expected_symbols=(),
            answerable=True,
            tags=(),
        ),
        EvaluationCase(
            id="q002",
            question="second question",
            expected_sources=("samples/second.cbl",),
            expected_symbols=(),
            answerable=True,
            tags=(),
        ),
        EvaluationCase(
            id="q003",
            question="unanswerable question",
            expected_sources=(),
            expected_symbols=(),
            answerable=False,
            tags=("unanswerable",),
        ),
    ]
    rankings_by_question = {
        "first question": [
            "samples/first.cbl",
            "samples/other.cbl",
        ],
        "second question": [
            "samples/other.cbl",
            "samples/second.cbl",
        ],
    }
    calls: list[tuple[str, int]] = []

    def retrieve_sources(
        question: str,
        limit: int,
    ) -> list[str]:
        calls.append((question, limit))
        return rankings_by_question[question]

    summary = evaluate_retrieval(
        cases,
        retrieve_sources,
        k=2,
    )

    assert calls == [
        ("first question", 2),
        ("second question", 2),
    ]
    assert summary.evaluated_cases == 2
    assert summary.hit_at_k == 1.0
    assert summary.mrr == 0.75

    assert len(summary.case_results) == 2

    first_result = summary.case_results[0]
    assert first_result.case_id == "q001"
    assert first_result.question == "first question"
    assert first_result.expected_sources == (
      "samples/first.cbl",
    )
    assert first_result.retrieved_sources == (
        "samples/first.cbl",
        "samples/other.cbl",
    )
    assert first_result.hit_at_k == 1.0
    assert first_result.reciprocal_rank == 1.0

    second_result = summary.case_results[1]
    assert second_result.case_id == "q002"
    assert second_result.retrieved_sources == (
        "samples/other.cbl",
        "samples/second.cbl",
    )
    assert second_result.hit_at_k == 1.0
    assert second_result.reciprocal_rank == 0.5
