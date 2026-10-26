from pathlib import Path

from legacy_rag.evaluation.dataset import load_evaluation_cases


def test_load_evaluation_cases_reads_fixed_dataset() -> None:
  project_root = Path(__file__).resolve().parents[2]
  dataset_path = (
      project_root
      / "data"
      / "evaluation"
      / "questions-v1.jsonl"
  )

  cases = load_evaluation_cases(dataset_path)

  assert len(cases) == 30

  answerable_cases = [
      case for case in cases if case.answerable
  ]
  unanswerable_cases = [
      case for case in cases if not case.answerable
  ]

  assert len(answerable_cases) == 24
  assert len(unanswerable_cases) == 6

  assert cases[0].id == "q001"
  assert cases[0].expected_sources == (
      "samples/customer-import.cbl",
  )

  assert all(
      case.expected_sources
      for case in answerable_cases
  )
  assert all(
      not case.expected_sources
      for case in unanswerable_cases
  )