import argparse
import json
from dataclasses import asdict
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from legacy_rag.evaluation.run_structured_baseline import metrics_from_report
from legacy_rag.evaluation.structured_baseline import (
    build_contextual_embedding_text,
    run_structured_baseline,
)


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Evaluate path-and-symbol contextual embeddings.")
    parser.add_argument("--data-root", type=Path, default=project_root / "data")
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--chroma-path", type=Path)
    parser.add_argument("--structured-baseline-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    dataset_path = (args.dataset_path or data_root / "evaluation" / "questions-v1.jsonl").resolve()
    chroma_path = (args.chroma_path or data_root / "chroma" / "contextual-structured-v1").resolve()
    structured_baseline_path = (
        args.structured_baseline_path
        or data_root / "evaluation" / "results" / "structured-baseline-v1.json"
    ).resolve()
    output_path = (
        args.output_path
        or data_root / "evaluation" / "results" / "contextual-structured-baseline-v1.json"
    ).resolve()

    collection = chromadb.PersistentClient(path=str(chroma_path)).get_or_create_collection(
        name="legacy-rag-contextual-structured-v1",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    result = run_structured_baseline(
        data_root=data_root,
        dataset_path=dataset_path,
        collection=collection,
        embed_texts=DefaultEmbeddingFunction(),
        embedding_text_builder=build_contextual_embedding_text,
        k=5,
    )

    structured_baseline = json.loads(structured_baseline_path.read_text(encoding="utf-8"))
    raw_metrics = structured_baseline["structured_metrics"]
    contextual_metrics = metrics_from_report(result.report)
    deltas = {
        name: contextual_metrics[name] - float(raw_metrics[name])
        for name in contextual_metrics
    }
    output = {
        "configuration": {
            "chroma_version": chromadb.__version__,
            "embedding_function": "default",
            "model": "all-MiniLM-L6-v2",
            "distance": "cosine",
            "chunking": "cobol-structure-v1",
            "embedding_input": "source-path-symbol-text-v1",
            "data_root": str(data_root),
            "dataset_path": str(dataset_path),
            "chroma_path": str(chroma_path),
            "structured_baseline_path": str(structured_baseline_path),
        },
        "chunk_count": result.chunk_count,
        "raw_structured_metrics": raw_metrics,
        "contextual_metrics": contextual_metrics,
        "deltas": deltas,
        "report": asdict(result.report),
        "retrieved_chunks_by_case_id": {
            case_id: [
                {
                    **asdict(chunk),
                    "score": round(chunk.score, 6),
                }
                for chunk in chunks
            ]
            for case_id, chunks in result.retrieved_chunks_by_case_id.items()
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"chunks={result.chunk_count}")
    print(f"hit_at_1={contextual_metrics['hit_at_1']:.4f}")
    print(f"hit_at_3={contextual_metrics['hit_at_3']:.4f}")
    print(f"hit_at_5={contextual_metrics['hit_at_5']:.4f}")
    print(f"mrr={contextual_metrics['mrr']:.4f}")
    print(f"mrr_delta={deltas['mrr']:+.4f}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
