import argparse
import json
from dataclasses import asdict
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import (
    DefaultEmbeddingFunction,
)

from legacy_rag.evaluation.baseline import (
    run_file_level_baseline,
)


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(
        description="Run the file-level retrieval baseline.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root / "data",
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
    )
    parser.add_argument(
        "--chroma-path",
        type=Path,
    )
    parser.add_argument(
        "--output-path",
        type=Path,
    )
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    dataset_path = (args.dataset_path or data_root / "evaluation" / "questions-v1.jsonl").resolve()
    chroma_path = (args.chroma_path or data_root / "chroma" / "baseline-v1").resolve()
    output_path = (
        args.output_path or data_root / "evaluation" / "results" / "file-level-baseline-v1.json"
    ).resolve()

    client = chromadb.PersistentClient(
        path=str(chroma_path),
    )
    collection = client.get_or_create_collection(
        name="legacy-rag-file-baseline-v1",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )

    embed_texts = DefaultEmbeddingFunction()

    report = run_file_level_baseline(
        data_root=data_root,
        dataset_path=dataset_path,
        collection=collection,
        embed_texts=embed_texts,
        k=5,
    )

    output = {
        "configuration": {
            "chroma_version": chromadb.__version__,
            "embedding_function": "default",
            "model": "all-MiniLM-L6-v2",
            "distance": "cosine",
            "chunking": "file-level",
            "k": 5,
            "data_root": str(data_root),
            "dataset_path": str(dataset_path),
            "chroma_path": str(chroma_path),
        },
        "report": asdict(report),
    }

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"evaluated_cases={report.evaluated_cases}")
    print(f"hit_at_5={report.hit_at_k:.4f}")
    print(f"mrr={report.mrr:.4f}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
