from collections.abc import Callable
from time import perf_counter

from pydantic import TypeAdapter

from legacy_rag.evaluation.dataset import EvaluationCase
from legacy_rag.generation.models import GeneratedAnswer, QueryReason


def _validate_response(payload: dict) -> None:
    status = payload["status"]
    TypeAdapter(QueryReason | None).validate_python(payload["reason"])
    if status == "answered":
        GeneratedAnswer.model_validate({key: payload[key] for key in ("status", "claims", "reason")})
        if not isinstance(payload["answer"], str) or not payload["answer"].strip():
            raise ValueError("missing answer")
        if not isinstance(payload["sources"], list) or not payload["sources"]:
            raise ValueError("missing cited sources")
        source_ids = {source["chunk_id"] for source in payload["sources"]}
        if any(not claim["chunk_ids"] or not set(claim["chunk_ids"]) <= source_ids
               for claim in payload["claims"]):
            raise ValueError("unlinked citations")
    elif status in {"refused", "unavailable"}:
        if payload["answer"] is not None or payload["claims"] or payload["sources"]:
            raise ValueError("invalid non-answer")
        if status == "unavailable" and payload["reason"] != "generation_unavailable":
            raise ValueError("invalid unavailable reason")
        if status == "refused" and payload["reason"] not in {
            "no_evidence", "insufficient_evidence", "conflicting_evidence", "invalid_citations",
        }:
            raise ValueError("invalid refusal reason")
    else:
        raise ValueError("unknown status")


def collect_generation(
    cases: list[EvaluationCase],
    query: Callable[[str], dict],
    *,
    on_result: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Collect all cases once. Query receives only the question, never ground truth."""
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("duplicate case IDs")
    records = []
    for case in cases:
        started = perf_counter()
        observation = {}
        try:
            result = query(case.question)
            if not isinstance(result, dict):
                raise TypeError("query observation must be an object")
            observation = result
            if observation.get("error_kind"):
                status = "error"
            else:
                _validate_response(observation["response"])
                status = observation["response"]["status"]
        except Exception:  # noqa: BLE001 -- never persist exception text containing request data
            status = "error"
            observation["error_kind"] = "collection_or_contract_error"
        record = {
            "case_id": case.id, "question": case.question, "answerable": case.answerable,
            "expected_sources": list(case.expected_sources),
            "expected_symbols": list(case.expected_symbols),
            **observation, "status": status,
            "collection_elapsed_seconds": round(perf_counter() - started, 6),
        }
        records.append(record)
        if on_result is not None:
            on_result(record)
    return records


def make_review_template(records: list[dict], rubric: dict[str, list[str]]) -> list[dict]:
    """Prepare post-generation judgments; no model is used for scoring."""
    return [{
        "case_id": record["case_id"], "rubric_version": "answer-rubric-v1",
        "required_points": rubric[record["case_id"]],
        "answer_correct": None, "answer_complete": None, "refusal_correct": None,
        "reviewer": None, "reviewer_kind": None, "notes": "",
        "atomic_facts": [{
            "claim_index": index, "text": claim["text"],
            "grounding": "pending", "citation_support": "pending",
        } for index, claim in enumerate(record.get("response", {}).get("claims", []))],
    } for record in records]
