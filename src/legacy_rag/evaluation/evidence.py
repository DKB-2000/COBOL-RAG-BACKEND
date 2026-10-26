import json
import re
from dataclasses import dataclass
from pathlib import Path

from legacy_rag.evaluation.dataset import EvaluationCase


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    source_path: str
    anchors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    chunk_id: str
    source_path: str
    text: str


def contains_code(text: str, fragment: str) -> bool:
    normalized_text = " ".join(text.upper().split())
    normalized_fragment = " ".join(fragment.upper().split())
    if not normalized_fragment:
        raise ValueError("code fragment must not be empty")
    pattern = rf"(?<![A-Z0-9-]){re.escape(normalized_fragment)}(?![A-Z0-9-])"
    return re.search(pattern, normalized_text) is not None


def load_evidence_requirements(
    path: Path,
    *,
    cases: list[EvaluationCase],
    data_root: Path,
) -> dict[str, tuple[EvidenceRequirement, ...]]:
    answerable = {case.id: case for case in cases if case.answerable}
    requirements: dict[str, tuple[EvidenceRequirement, ...]] = {}
    source_texts: dict[str, str] = {}
    resolved_root = data_root.resolve()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        case_id = record["case_id"]
        if case_id not in answerable or case_id in requirements:
            raise ValueError(f"unknown or duplicate evidence case: {case_id}")
        units = tuple(
            EvidenceRequirement(item["source_path"], tuple(item["anchors"]))
            for item in record["required_evidence"]
        )
        if not units:
            raise ValueError(f"empty evidence requirements: {case_id}")
        for unit in units:
            if unit.source_path not in answerable[case_id].expected_sources or not unit.anchors:
                raise ValueError(f"invalid evidence requirement: {case_id}")
            source = (resolved_root / unit.source_path).resolve()
            if not source.is_relative_to(resolved_root):
                raise ValueError("evidence source is outside data root")
            if unit.source_path not in source_texts:
                source_texts[unit.source_path] = source.read_text(encoding="utf-8")
            if not all(
                contains_code(source_texts[unit.source_path], anchor) for anchor in unit.anchors
            ):
                raise ValueError(f"evidence anchors not found in source: {case_id}")
        requirements[case_id] = units
    if set(requirements) != set(answerable):
        raise ValueError("evidence requirements must cover every answerable case")
    return requirements


def evaluate_chunk_evidence(
    cases: list[EvaluationCase],
    requirements: dict[str, tuple[EvidenceRequirement, ...]],
    rankings: dict[str, list[EvidenceChunk]],
    *,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict:
    if not ks or any(k < 1 for k in ks):
        raise ValueError("k must be positive")
    answerable = [case for case in cases if case.answerable]
    case_results = []
    for case in answerable:
        units = requirements[case.id]
        if not units or not case.expected_symbols:
            raise ValueError(f"missing expected evidence or symbols: {case.id}")
        results_by_k = {}
        for k in ks:
            chunks = rankings[case.id][:k]
            correct_source_chunks = [c for c in chunks if c.source_path in case.expected_sources]
            found_symbols = [
                symbol
                for symbol in case.expected_symbols
                if any(contains_code(chunk.text, symbol) for chunk in correct_source_chunks)
            ]
            found_units = [
                index
                for index, unit in enumerate(units)
                if any(
                    chunk.source_path == unit.source_path
                    and all(contains_code(chunk.text, anchor) for anchor in unit.anchors)
                    for chunk in chunks
                )
            ]
            results_by_k[str(k)] = {
                "symbol_coverage": len(found_symbols) / len(case.expected_symbols),
                "evidence_hit": float(bool(found_units)),
                "evidence_coverage": len(found_units) / len(units),
                "evidence_complete": float(len(found_units) == len(units)),
                "source_hit": float(bool(correct_source_chunks)),
                "context_characters": sum(len(chunk.text) for chunk in chunks),
                "matched_symbols": found_symbols,
                "missing_symbols": [s for s in case.expected_symbols if s not in found_symbols],
                "missing_evidence": [
                    {"source_path": unit.source_path, "anchors": list(unit.anchors)}
                    for index, unit in enumerate(units)
                    if index not in found_units
                ],
                "retrieved_chunk_ids": [chunk.chunk_id for chunk in chunks],
            }
        case_results.append({"case_id": case.id, "question": case.question, "by_k": results_by_k})

    metrics = {}
    for k in ks:
        values = [case["by_k"][str(k)] for case in case_results]
        metrics[str(k)] = {
            name: sum(value[name] for value in values) / len(values) if values else 0.0
            for name in [
                "symbol_coverage",
                "evidence_hit",
                "evidence_coverage",
                "evidence_complete",
                "source_hit",
                "context_characters",
            ]
        }
    return {"evaluated_cases": len(answerable), "metrics": metrics, "case_results": case_results}
