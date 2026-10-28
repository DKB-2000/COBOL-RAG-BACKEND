from collections import Counter
from math import ceil, isfinite


def _rate(passed: int, denominator: int, pending: int = 0) -> dict:
    return {
        "passed": passed, "denominator": denominator, "pending": pending,
        "rate": passed / denominator if denominator and not pending else None,
    }


def summarize_generation(records: list[dict], reviews: list[dict] | None = None) -> dict:
    by_id = {record["case_id"]: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("duplicate result IDs")
    reviews = reviews or []
    judgments = {review["case_id"]: review for review in reviews}
    if len(judgments) != len(reviews) or not set(judgments) <= set(by_id):
        raise ValueError("unknown or duplicate review IDs")
    answerable = [record for record in records if record["answerable"]]
    unanswerable = [record for record in records if not record["answerable"]]
    counts = Counter(record["status"] for record in records)
    correct = complete_grounded = refusal_correct = 0
    pending_correct = pending_grounded = pending_refusal = 0
    supported = citation_supported = judged_facts = 0
    pending_facts = unreviewed_claims = 0
    valid_ids = total_ids = 0
    reviewer_kinds = Counter()
    for record in records:
        review = judgments.get(record["case_id"], {})
        facts = review.get("atomic_facts", [])
        claims = record.get("response", {}).get("claims", [])
        for key in ("answer_correct", "answer_complete", "refusal_correct"):
            if review.get(key) is not None and type(review[key]) is not bool:
                raise ValueError("judgments must be booleans or null")
        covered = set()
        for fact in facts:
            index = fact["claim_index"]
            if type(index) is not int or not 0 <= index < len(claims) or not fact["text"].strip():
                raise ValueError("invalid atomic fact")
            if any(fact.get(key) not in {"supported", "contradicted", "insufficient", "pending"}
                   for key in ("grounding", "citation_support")):
                raise ValueError("invalid fact judgment")
            covered.add(index)
            if fact["grounding"] == "pending" or fact["citation_support"] == "pending":
                pending_facts += 1
            else:
                judged_facts += 1
                supported += fact["grounding"] == "supported"
                citation_supported += fact["citation_support"] == "supported"
        has_judgment = (
            any(review.get(key) is not None for key in
                ("answer_correct", "answer_complete", "refusal_correct"))
            or any(f.get("grounding") != "pending" or f.get("citation_support") != "pending"
                   for f in facts)
        )
        if has_judgment:
            if not review.get("reviewer") or review.get("reviewer_kind") not in {
                "human", "codex_orchestrator",
            } or review.get("rubric_version") != "answer-rubric-v1":
                raise ValueError("reviewer attribution and rubric version are required")
            reviewer_kinds[review["reviewer_kind"]] += 1
        unreviewed_claims += len(claims) - len(covered)
        returned_ids = {s["chunk_id"] for s in record.get("response", {}).get("sources", [])}
        for claim in claims:
            total_ids += len(claim["chunk_ids"])
            valid_ids += sum(chunk_id in returned_ids for chunk_id in claim["chunk_ids"])
        if record["answerable"]:
            if record["status"] == "answered":
                correct += review.get("answer_correct") is True
                pending_correct += review.get("answer_correct") is None
                known_failure = (
                    review.get("answer_correct") is False or review.get("answer_complete") is False
                    or any(f.get("grounding") in {"contradicted", "insufficient"}
                           or f.get("citation_support") in {"contradicted", "insufficient"}
                           for f in facts)
                )
                fully_judged = (
                    review.get("answer_correct") is True and review.get("answer_complete") is True
                    and bool(claims) and covered == set(range(len(claims)))
                    and all(f["grounding"] == f["citation_support"] == "supported" for f in facts)
                )
                complete_grounded += fully_judged
                pending_grounded += not fully_judged and not known_failure
        elif record["status"] == "refused":
            reason = record.get("response", {}).get("reason")
            if reason in {"no_evidence", "insufficient_evidence"}:
                refusal_correct += review.get("refusal_correct") is True
                pending_refusal += review.get("refusal_correct") is None
    durations = [record["query_elapsed_seconds"] for record in records
                 if record.get("query_elapsed_seconds") is not None]
    if any(not isfinite(value) or value < 0 for value in durations):
        raise ValueError("invalid latency")
    durations.sort()
    latency = {"n": len(durations), "method": "nearest_rank", "scope": "query_http_only",
               "p50_seconds": durations[ceil(len(durations) * 0.5) - 1] if durations else None,
               "p95_seconds": durations[ceil(len(durations) * 0.95) - 1] if durations else None}
    return {
        "total": len(records), "answerable": len(answerable), "unanswerable": len(unanswerable),
        "status_counts": dict(counts),
        "answer_provided": _rate(sum(r["status"] == "answered" for r in answerable), len(answerable)),
        "answer_correct": _rate(correct, len(answerable), pending_correct),
        "grounded_complete_answer": _rate(complete_grounded, len(answerable), pending_grounded),
        "correct_refusal": _rate(refusal_correct, len(unanswerable), pending_refusal),
        "semantic_grounding": _rate(supported, judged_facts, pending_facts + unreviewed_claims),
        "citation_support": _rate(citation_supported, judged_facts, pending_facts + unreviewed_claims),
        "citation_id_linkage": _rate(valid_ids, total_ids),
        "unreviewed_claims": unreviewed_claims, "pending_atomic_facts": pending_facts,
        "reviewer_kinds": dict(reviewer_kinds), "latency": latency,
        "api_query_attempts": sum(bool(r.get("api_query_attempted")) for r in records),
        "actual_token_usage": None, "actual_cost_usd": None,
    }
