"""Measure public candidate recall using cached ONNX and ephemeral Chroma only."""
import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import chromadb
from chromadb.config import Settings

from legacy_rag.api.dependencies import ApiSettings
from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES
from legacy_rag.api.services import StructuredDocumentIndexer, VectorChunkSearcher
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import (
    contains_code,
    evaluate_chunk_evidence,
    load_evidence_requirements,
)
from legacy_rag.retrieval.chroma_store import ChromaChunkStore
from legacy_rag.retrieval.context import assemble_context
from legacy_rag.retrieval.embedding import IdentifierAwareOnnxEmbedding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new filename")
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    cases = load_evaluation_cases(data / "evaluation/questions-v1.jsonl")
    requirements = load_evidence_requirements(
        data / "evaluation/evidence-v1.jsonl", cases=cases, data_root=data,
    )
    prior = json.loads(
        (data / "evaluation/results/identifier-aware-retrieval-v1.json").read_text(
            encoding="utf-8",
        )
    )["profiles"]["identifier-aware"]["cases"]
    encoder = IdentifierAwareOnnxEmbedding(ApiSettings().model_dir.resolve())
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    store = ChromaChunkStore(client.create_collection(
        "candidate-diagnosis", embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    ))
    indexer = StructuredDocumentIndexer(
        data_root=data, store=store, embed_texts=encoder,
        allowed_source_hashes=PUBLIC_SOURCE_HASHES,
    )
    indexed = indexer.index(source_paths=list(PUBLIC_SOURCE_HASHES), rebuild=False)
    assert indexed.indexed_documents == 5 and indexed.indexed_chunks == 52
    searcher = VectorChunkSearcher(store=store, embed_texts=encoder)
    budgets = (10, 20, 30, 52)
    raw = {k: {} for k in budgets}
    selected = {k: {} for k in budgets}
    matches = []
    ranks = []
    for case in cases:
        for k in budgets:
            results = searcher.search(query=case.question, limit=k)
            raw[k][case.id] = results
            selected[k][case.id] = list(assemble_context(results))
        baseline_ids = [r.chunk_id for r in selected[10][case.id]]
        if baseline_ids == prior[case.id]["context_ids"]:
            matches.append(case.id)
        if case.answerable:
            units = []
            for unit in requirements[case.id]:
                hits = [
                    (rank, row) for rank, row in enumerate(raw[52][case.id], 1)
                    if row.source_path == unit.source_path
                    and all(contains_code(row.text, anchor) for anchor in unit.anchors)
                ]
                units.append({
                    "source_path": unit.source_path,
                    "best_rank": hits[0][0] if hits else None,
                    "symbol": hits[0][1].symbol if hits else None,
                    "chunk_id": hits[0][1].chunk_id if hits else None,
                })
            ranks.append({"case_id": case.id, "question": case.question, "units": units})
    assert len(matches) == len(cases), "Current top10 context differs from saved baseline"
    metrics = {}
    for k in budgets:
        pool = evaluate_chunk_evidence(cases, requirements, raw[k], ks=(k,))
        context = evaluate_chunk_evidence(cases, requirements, selected[k], ks=(10,))
        pool_complete = [r["case_id"] for r in pool["case_results"]
                         if r["by_k"][str(k)]["evidence_complete"] == 1]
        context_complete = [r["case_id"] for r in context["case_results"]
                            if r["by_k"]["10"]["evidence_complete"] == 1]
        metrics[str(k)] = {
            "candidate_complete_cases": pool_complete,
            "selected_complete_cases": context_complete,
            "candidate_complete_count": len(pool_complete),
            "selected_complete_count": len(context_complete),
            "selected_ids": {c.id: [r.chunk_id for r in selected[k][c.id]] for c in cases},
            "candidate_ids": {c.id: [r.chunk_id for r in raw[k][c.id]] for c in cases},
        }
        print(f"k={k}: candidate={len(pool_complete)}/24; context={len(context_complete)}/24")
    inputs = [data / "evaluation/questions-v1.jsonl", data / "evaluation/evidence-v1.jsonl",
              data / "evaluation/results/identifier-aware-retrieval-v1.json",
              *[data / path for path in PUBLIC_SOURCE_HASHES]]
    report = {
        "schema_version": "retrieval-candidates-v1", "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": "identifier-aware", "documents": 5, "chunks": 52,
        "answerable_cases": 24, "total_cases": 30, "generation_calls": 0,
        "index": "ephemeral Chroma; persistent stores unchanged",
        "context_policy": {"max_chunks": 10, "max_chars": 4000},
        "baseline_context_matches": matches, "metrics": metrics, "evidence_ranks": ranks,
        "input_hashes": {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
                         for p in inputs},
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "Candidate recall is not answer accuracy or reranker performance.",
            "Gold evidence is used only after ranking for offline measurement.",
            "52 candidates cover the entire small corpus; not a scalability result.",
            "Unanswerable questions are searched but refusal quality is not evaluated.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
