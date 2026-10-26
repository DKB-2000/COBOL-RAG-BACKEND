import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import (
    EvidenceChunk,
    contains_code,
    evaluate_chunk_evidence,
    load_evidence_requirements,
)
from legacy_rag.evaluation.run_evidence_evaluation import load_saved_rankings
from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_files
from legacy_rag.retrieval.context_expansion import build_cobol_relations, expand_related_chunks


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Evaluate one-hop COBOL context expansion offline."
    )
    parser.add_argument("--data-root", type=Path, default=project_root / "data")
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument("--baseline-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    dataset_path = (args.dataset_path or data_root / "evaluation/questions-v1.jsonl").resolve()
    evidence_path = (args.evidence_path or data_root / "evaluation/evidence-v1.jsonl").resolve()
    baseline_path = (
        args.baseline_path
        or data_root / "evaluation/results/multilingual-structured-baseline-v1.json"
    ).resolve()
    output_path = (
        args.output_path or data_root / "evaluation/results/context-expansion-v1.json"
    ).resolve()
    source_paths = sorted((data_root / "samples").glob("*.cbl"))
    input_paths = [dataset_path, evidence_path, baseline_path, *source_paths]
    if output_path in input_paths:
        raise ValueError("output path must not overwrite evaluation inputs")
    cases = load_evaluation_cases(dataset_path)
    requirements = load_evidence_requirements(evidence_path, cases=cases, data_root=data_root)
    documents = {d.source_path: d for d in load_cobol_files(source_paths, data_root=data_root)}
    chunks = [c for doc in documents.values() for c in chunk_cobol_structure(doc)]
    by_id = {c.chunk_id: c for c in chunks}
    saved_rankings = load_saved_rankings(baseline_path, cases=cases, documents=documents)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline["configuration"]["chunking"] != "cobol-structure-v1":
        raise ValueError("context expansion requires structural chunks")
    rankings = {}
    for case_id, ranked in saved_rankings.items():
        rankings[case_id] = []
        for saved in ranked:
            c = by_id[saved.chunk_id]
            if c.source_path != saved.source_path or c.text != saved.text:
                raise ValueError(f"baseline chunk mismatch: {case_id}")
            rankings[case_id].append(c)
    relations = build_cobol_relations(chunks)
    contexts = {name: {} for name in ("raw_top5", "raw_top10", "budgeted_top10", "expanded_top5")}
    traces = {}
    for case_id, ranked in rankings.items():
        contexts["raw_top5"][case_id] = ranked[:5]
        contexts["raw_top10"][case_id] = ranked[:10]
        budgeted = expand_related_chunks(ranked[:10], chunks, {})
        expanded = expand_related_chunks(ranked[:5], chunks, relations)
        contexts["budgeted_top10"][case_id] = list(budgeted.chunks)
        contexts["expanded_top5"][case_id] = list(expanded.chunks)
        traces[case_id] = {
            "seed_ids": [c.chunk_id for c in ranked[:5]],
            "additions": [asdict(item) for item in expanded.additions],
            "skipped_ids": list(expanded.skipped_ids),
            "baseline_skipped_ids": list(budgeted.skipped_ids),
        }
    reports = {}
    for name, selected in contexts.items():
        report = evaluate_chunk_evidence(
            cases,
            requirements,
            {
                case_id: [EvidenceChunk(c.chunk_id, c.source_path, c.text) for c in context]
                for case_id, context in selected.items()
            },
            ks=(10,),
        )
        reports[name] = {
            "evaluated_cases": report["evaluated_cases"],
            "metrics": {
                **report["metrics"]["10"],
                "mean_chunk_count": sum(len(value) for value in selected.values()) / len(selected),
                "max_context_characters": max(
                    sum(len(c.text) for c in value) for value in selected.values()
                ),
            },
            "case_results": [
                {"case_id": c["case_id"], "question": c["question"], **c["by_k"]["10"]}
                for c in report["case_results"]
            ],
        }
    token_lengths = baseline["truncation"]["document_token_lengths"]
    failure_analysis = []
    for result in reports["raw_top5"]["case_results"]:
        if result["evidence_complete"]:
            continue
        ranks = {c.chunk_id: i + 1 for i, c in enumerate(rankings[result["case_id"]])}
        missing = []
        for unit in result["missing_evidence"]:
            matches = [
                c
                for c in chunks
                if c.source_path == unit["source_path"]
                and all(contains_code(c.text, anchor) for anchor in unit["anchors"])
            ]
            missing.append(
                {
                    **unit,
                    "matching_chunk_ids": [c.chunk_id for c in matches],
                    "first_saved_rank": min(
                        (ranks[c.chunk_id] for c in matches if c.chunk_id in ranks), default=None
                    ),
                    "matching_chunks_truncated": [
                        c.chunk_id for c in matches if token_lengths[c.chunk_id] > 128
                    ],
                }
            )
        failure_analysis.append({"case_id": result["case_id"], "missing_evidence": missing})
    output = {
        "configuration": {
            "method": "cobol-relations-1hop-v1",
            "seed_count": 5,
            "max_chunks": 10,
            "max_characters": 4000,
            "selection_priority": [
                "using-contract",
                "perform/perform-caller",
                "call/call-caller",
                "declaration",
            ],
            "input_hashes": {str(p): sha256(p.read_bytes()).hexdigest() for p in input_paths},
        },
        "reports": reports,
        "expansion_trace": traces,
        "relations": {key: [asdict(r) for r in edges] for key, edges in relations.items()},
        "failure_analysis": failure_analysis,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, report in reports.items():
        metrics = report["metrics"]
        print(
            f"{name}: complete={metrics['evidence_complete']:.4f} "
            f"chars={metrics['context_characters']:.1f} chunks={metrics['mean_chunk_count']:.2f}"
        )
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
