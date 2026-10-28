"""Evaluate saved reranker scores offline using the existing evidence and context policy."""
import argparse
import json
from hashlib import sha256
from math import ceil
from pathlib import Path

from legacy_rag.api.public_corpus import load_public_chunks
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import evaluate_chunk_evidence, load_evidence_requirements
from legacy_rag.retrieval.context import assemble_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new filename")
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    source = data / "evaluation/results/retrieval-candidates-v1.json"
    baseline = json.loads(source.read_text(encoding="utf-8"))
    for path, digest in baseline["input_hashes"].items():
        assert sha256((root / path).read_bytes()).hexdigest() == digest
    metadata = json.loads(args.scores.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert metadata["output_sha256"] == sha256(args.scores.read_bytes()).hexdigest()
    rows = [json.loads(line) for line in args.scores.read_text(encoding="utf-8").splitlines()]
    cases = load_evaluation_cases(data / "evaluation/questions-v1.jsonl")
    assert len(rows) == len(cases) and {r["case_id"] for r in rows} == {c.id for c in cases}
    chunks = load_public_chunks(data)
    requirements = load_evidence_requirements(
        data / "evaluation/evidence-v1.jsonl", cases=cases, data_root=data,
    )
    selected = {}
    for row in rows:
        expected = baseline["metrics"]["30"]["candidate_ids"][row["case_id"]]
        assert len(row["ranked_ids"]) == 30 and set(row["ranked_ids"]) == set(expected)
        selected[row["case_id"]] = list(assemble_context(
            chunks[chunk_id] for chunk_id in row["ranked_ids"]
        ))
    evidence = evaluate_chunk_evidence(cases, requirements, selected, ks=(10,))
    before = set(baseline["metrics"]["10"]["selected_complete_cases"])
    after = {r["case_id"] for r in evidence["case_results"]
             if r["by_k"]["10"]["evidence_complete"] == 1}
    times = sorted(row["elapsed_seconds"] for row in rows)
    result = {
        "schema_version": "reranker-evaluation-v1", "metadata": metadata,
        "baseline_sha256": sha256(source.read_bytes()).hexdigest(),
        "input_hashes": baseline["input_hashes"], "before_complete": sorted(before),
        "after_complete": sorted(after), "improved": sorted(after - before),
        "regressed": sorted(before - after), "before_count": len(before),
        "after_count": len(after), "denominator": 24, "generation_calls": 0,
        "rerank_seconds": {"n": len(times), "p50": times[ceil(len(times) * .5) - 1],
                           "p95": times[ceil(len(times) * .95) - 1],
                           "scope": "reranking only, includes tokenization; excludes search/load"},
        "truncated_pairs": sum(row["truncated_pairs"] for row in rows),
        "evidence": evidence, "rankings": rows,
        "limitations": ["Development set, not holdout or answer accuracy.",
                        "No refusal/generation evaluation; no API integration.",
                        "One fixed candidate budget/model/512-token run, no parameter search."],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Evidence: {len(before)} -> {len(after)}/24")
    print("Improved:", sorted(after - before), "Regressed:", sorted(before - after))
    print("Rerank seconds:", result["rerank_seconds"])


if __name__ == "__main__":
    main()
