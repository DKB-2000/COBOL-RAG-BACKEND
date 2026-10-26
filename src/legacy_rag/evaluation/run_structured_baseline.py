import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from legacy_rag.evaluation.metrics import hit_at_k
from legacy_rag.evaluation.runner import RetrievalReport
from legacy_rag.evaluation.structured_baseline import run_structured_baseline


def metrics_from_report(report: RetrievalReport) -> dict[str, float]:
    def mean_hit(k: int) -> float:
        scores = [
            hit_at_k(
                list(result.retrieved_sources),
                set(result.expected_sources),
                k=k,
            )
            for result in report.case_results
        ]
        return sum(scores) / len(scores) if scores else 0.0

    return {
        "hit_at_1": mean_hit(1),
        "hit_at_3": mean_hit(3),
        "hit_at_5": mean_hit(5),
        "mrr": report.mrr,
    }


def _metrics_from_saved_report(saved: dict[str, Any]) -> dict[str, float]:
    case_results = saved["report"]["case_results"]

    def mean_hit(k: int) -> float:
        scores = [
            hit_at_k(
                result["retrieved_sources"],
                set(result["expected_sources"]),
                k=k,
            )
            for result in case_results
        ]
        return sum(scores) / len(scores) if scores else 0.0

    return {
        "hit_at_1": mean_hit(1),
        "hit_at_3": mean_hit(3),
        "hit_at_5": mean_hit(5),
        "mrr": float(saved["report"]["mrr"]),
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Compare structured and file-level retrieval.")
    parser.add_argument("--data-root", type=Path, default=project_root / "data")
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--chroma-path", type=Path)
    parser.add_argument("--file-baseline-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    dataset_path = (args.dataset_path or data_root / "evaluation" / "questions-v1.jsonl").resolve()
    chroma_path = (args.chroma_path or data_root / "chroma" / "structured-v1").resolve()
    file_baseline_path = (
        args.file_baseline_path
        or data_root / "evaluation" / "results" / "file-level-baseline-v1.json"
    ).resolve()
    output_path = (
        args.output_path
        or data_root / "evaluation" / "results" / "structured-baseline-v1.json"
    ).resolve()

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(
        name="legacy-rag-structured-baseline-v1",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    embed_texts = DefaultEmbeddingFunction()
    result = run_structured_baseline(
        data_root=data_root,
        dataset_path=dataset_path,
        collection=collection,
        embed_texts=embed_texts,
        k=5,
    )
    filtered_result = run_structured_baseline(
        data_root=data_root,
        dataset_path=dataset_path,
        collection=collection,
        embed_texts=embed_texts,
        k=5,
        metadata_filter={"language": "cobol"},
    )

    file_baseline = json.loads(file_baseline_path.read_text(encoding="utf-8"))
    file_metrics = _metrics_from_saved_report(file_baseline)
    structured_metrics = metrics_from_report(result.report)
    language_filtered_metrics = metrics_from_report(filtered_result.report)
    deltas = {
        name: structured_metrics[name] - file_metrics[name]
        for name in structured_metrics
    }
    output = {
        "configuration": {
            "chroma_version": chromadb.__version__,
            "embedding_function": "default",
            "model": "all-MiniLM-L6-v2",
            "distance": "cosine",
            "chunking": "cobol-structure-v1",
            "data_root": str(data_root),
            "dataset_path": str(dataset_path),
            "chroma_path": str(chroma_path),
            "file_baseline_path": str(file_baseline_path),
        },
        "chunk_count": result.chunk_count,
        "file_level_metrics": file_metrics,
        "structured_metrics": structured_metrics,
        "language_filtered_metrics": language_filtered_metrics,
        "language_filter_deltas": {
            name: language_filtered_metrics[name] - structured_metrics[name]
            for name in structured_metrics
        },
        "deltas": deltas,
        "report": asdict(result.report),
        "retrieved_chunks_by_case_id": {
            case_id: [asdict(chunk) for chunk in chunks]
            for case_id, chunks in result.retrieved_chunks_by_case_id.items()
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"chunks={result.chunk_count}")
    print(f"hit_at_1={structured_metrics['hit_at_1']:.4f}")
    print(f"hit_at_3={structured_metrics['hit_at_3']:.4f}")
    print(f"hit_at_5={structured_metrics['hit_at_5']:.4f}")
    print(f"mrr={structured_metrics['mrr']:.4f}")
    print(f"mrr_delta={deltas['mrr']:+.4f}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
