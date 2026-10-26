from collections.abc import Callable
from dataclasses import dataclass

from legacy_rag.evaluation.dataset import EvaluationCase
from legacy_rag.evaluation.metrics import (
  hit_at_k,
  reciprocal_rank,
  summarize_rankings,
)


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
  case_id: str
  question: str
  expected_sources: tuple[str, ...]
  retrieved_sources: tuple[str, ...]
  hit_at_k: float
  reciprocal_rank: float


@dataclass(frozen=True, slots=True)
class RetrievalReport:
  evaluated_cases: int
  hit_at_k: float
  mrr: float
  case_results: tuple[RetrievalCaseResult, ...]


def evaluate_retrieval(
  cases: list[EvaluationCase],
  retrieve_sources: Callable[
      [str, int],
      list[str],
  ],
  *,
  k: int,
) -> RetrievalReport:
  rankings_by_case_id: dict[str, list[str]] = {}

  for case in cases:
      if not case.answerable:
          continue

      rankings_by_case_id[case.id] = retrieve_sources(
          case.question,
          k,
      )

  summary = summarize_rankings(
      cases,
      rankings_by_case_id,
      k=k,
  )

  case_results: list[RetrievalCaseResult] = []

  for case in cases:
      if not case.answerable:
          continue

      retrieved_sources = rankings_by_case_id[case.id]
      expected_sources = set(case.expected_sources)

      case_results.append(
          RetrievalCaseResult(
              case_id=case.id,
              question=case.question,
              expected_sources=case.expected_sources,
              retrieved_sources=tuple(retrieved_sources),
              hit_at_k=hit_at_k(
                  retrieved_sources,
                  expected_sources,
                  k=k,
              ),
              reciprocal_rank=reciprocal_rank(
                  retrieved_sources,
                  expected_sources,
              ),
          )
      )

  return RetrievalReport(
      evaluated_cases=summary.evaluated_cases,
      hit_at_k=summary.hit_at_k,
      mrr=summary.mrr,
      case_results=tuple(case_results),
  )