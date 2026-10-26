from dataclasses import dataclass

from legacy_rag.evaluation.dataset import EvaluationCase


def hit_at_k(
    retrieved_sources: list[str],
    expected_sources: set[str],
    *,
    k: int,
) -> float:
    retrieved_at_k = retrieved_sources[:k]

    return float(any(source in expected_sources for source in retrieved_at_k))


def reciprocal_rank(
    retrieved_sources: list[str],
    expected_sources: set[str],
) -> float:
    for rank, source in enumerate(
        retrieved_sources,
        start=1,
    ):
        if source in expected_sources:
            return 1.0 / rank

    return 0.0


@dataclass(frozen=True, slots=True)
class RetrievalSummary:
    evaluated_cases: int
    hit_at_k: float
    mrr: float


def summarize_rankings(
    cases: list[EvaluationCase],
    rankings_by_case_id: dict[str, list[str]],
    *,
    k: int,
) -> RetrievalSummary:
    answerable_cases = [case for case in cases if case.answerable]

    if not answerable_cases:
        return RetrievalSummary(
            evaluated_cases=0,
            hit_at_k=0.0,
            mrr=0.0,
        )

    hit_scores: list[float] = []
    reciprocal_ranks: list[float] = []

    for case in answerable_cases:
        retrieved_sources = rankings_by_case_id[case.id]
        expected_sources = set(case.expected_sources)

        hit_scores.append(
            hit_at_k(
                retrieved_sources,
                expected_sources,
                k=k,
            )
        )
        reciprocal_ranks.append(
            reciprocal_rank(
                retrieved_sources,
                expected_sources,
            )
        )

    evaluated_cases = len(answerable_cases)

    return RetrievalSummary(
        evaluated_cases=evaluated_cases,
        hit_at_k=sum(hit_scores) / evaluated_cases,
        mrr=sum(reciprocal_ranks) / evaluated_cases,
    )
