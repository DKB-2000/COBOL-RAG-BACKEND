import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EvaluationCase:
  id: str
  question: str
  expected_sources: tuple[str, ...]
  expected_symbols: tuple[str, ...]
  answerable: bool
  tags: tuple[str, ...]


def load_evaluation_cases(
  path: Path,
) -> list[EvaluationCase]:
  cases: list[EvaluationCase] = []

  for line in path.read_text(
      encoding="utf-8",
  ).splitlines():
      if not line.strip():
          continue

      record = json.loads(line)
      cases.append(
          EvaluationCase(
              id=record["id"],
              question=record["question"],
              expected_sources=tuple(
                  record["expected_sources"]
              ),
              expected_symbols=tuple(
                  record["expected_symbols"]
              ),
              answerable=record["answerable"],
              tags=tuple(record["tags"]),
          )
      )

  return cases