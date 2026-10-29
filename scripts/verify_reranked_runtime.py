"""Compare a loopback runtime's public retrieval with frozen BGE contexts; no /query."""
import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from pathlib import Path
from time import perf_counter

import httpx
from evaluate_generation import HttpProbe, expected_context_ids, json_write

from legacy_rag.api.public_corpus import load_public_chunks
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import evaluate_chunk_evidence, load_evidence_requirements
from legacy_rag.retrieval.context import assemble_context

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8015)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.output.exists():
        raise FileExistsError("output exists; preserve previous verification")
    reference = json.loads((DATA / "evaluation/results/reranker-api-verification-v1.json")
                           .read_text(encoding="utf-8"))
    for name, digest in reference["input_hashes"].items():
        if sha256((PROJECT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("fixed public evaluation changed")
    cases = load_evaluation_cases(DATA / "evaluation/questions-v1.jsonl")
    approved = load_public_chunks(DATA)
    if len(cases) != 30 or sum(case.answerable for case in cases) != 24 or len(approved) != 52:
        raise ValueError("expected 30 public cases and 52 chunks")
    expected = expected_context_ids(approved, "identifier-aware", "bge-int8")
    rankings = json.loads((DATA / "evaluation/results/reranker-int8-length-v1.json")
                          .read_text(encoding="utf-8"))
    expected_ranks = {row["case_id"]: row["ranked_ids"] for row in rankings["rankings"]}
    requirements = load_evidence_requirements(
        DATA / "evaluation/evidence-v1.jsonl", cases=cases, data_root=DATA)
    selected, observations = {}, []
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", trust_env=False,
                      timeout=httpx.Timeout(300, connect=5)) as client:
        client.get("/health", timeout=5).raise_for_status()
        client.get("/ready").raise_for_status()
        probe = HttpProbe(client, approved, search_limit=30)
        for case in cases:
            started = perf_counter()
            candidates = probe.search(case.question)
            elapsed = round(perf_counter() - started, 6)
            selected[case.id] = assemble_context(candidates)
            ids = [chunk.chunk_id for chunk in selected[case.id]]
            if len(candidates) != 30:
                raise ValueError("expected 30 ranked candidates")
            observations.append({
                "case_id": case.id, "elapsed_seconds": elapsed,
                "ranked_ids": [chunk.chunk_id for chunk in candidates], "context_ids": ids,
                "context_matches": ids == expected[case.id],
                "full_ranking_matches": [chunk.chunk_id for chunk in candidates] == expected_ranks[case.id],
                "context_characters": sum(len(chunk.text) for chunk in selected[case.id]),
            })
            print(case.id, elapsed, "context_matches", ids == expected[case.id], flush=True)
    evidence = evaluate_chunk_evidence(cases, requirements, selected, ks=(10,))
    complete = sorted(row["case_id"] for row in evidence["case_results"]
                      if row["by_k"]["10"]["evidence_complete"] == 1)
    before = reference["profiles"]["bge-int8"]["complete_cases"]
    mismatches = [row["case_id"] for row in observations if not row["context_matches"]]
    times = sorted(row["elapsed_seconds"] for row in observations)
    report = {
        "schema_version": "reranked-runtime-verification-v1",
        "created_at_utc": datetime.now(UTC).isoformat(), "port": args.port,
        "generation_calls": 0, "query_calls": 0, "cases": 30,
        "context_capture_mode": "reconstructed from actual /search limit30; not a model prompt capture",
        "context_matches": 30 - len(mismatches), "context_mismatches": mismatches,
        "full_ranking_mismatches": [row["case_id"] for row in observations
                                    if not row["full_ranking_matches"]],
        "complete_cases": complete, "evidence_count": len(complete), "denominator": 24,
        "regressed_from_windows": sorted(set(before) - set(complete)),
        "improved_from_windows": sorted(set(complete) - set(before)),
        "http_seconds": {"n": 30, "p50": times[ceil(30 * .5) - 1],
                         "p95": times[ceil(30 * .95) - 1]},
        "measurement_scope": "sequential warm actual /search limit30, different fixed questions",
        "percentile_method": "nearest_rank", "input_hashes": reference["input_hashes"],
        "observations": observations, "evidence": evidence,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_write(args.output, report)
    if mismatches or complete != before:
        raise RuntimeError("runtime differs from frozen BGE contexts/evidence; report preserved")
    print("runtime_contexts_match=30/30 evidence=22/24 generation_calls=0", flush=True)


if __name__ == "__main__":
    main()
