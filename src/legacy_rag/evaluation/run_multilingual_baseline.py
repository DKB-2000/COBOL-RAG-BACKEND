import argparse
import json
from dataclasses import asdict
from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path

import chromadb
from huggingface_hub import snapshot_download

from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import (
    EvidenceChunk,
    evaluate_chunk_evidence,
    load_evidence_requirements,
)
from legacy_rag.evaluation.multilingual_embedding import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_REVISION,
    MultilingualOnnxEmbedding,
    WindowedMultilingualOnnxEmbedding,
)
from legacy_rag.evaluation.run_evidence_evaluation import load_saved_rankings
from legacy_rag.evaluation.run_structured_baseline import metrics_from_report
from legacy_rag.evaluation.structured_baseline import (
    build_contextual_embedding_text,
    run_structured_baseline,
)
from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_files


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Compare local multilingual contextual embeddings."
    )
    parser.add_argument("--data-root", type=Path, default=project_root / "data")
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument("--baseline-path", type=Path)
    parser.add_argument("--chroma-path", type=Path)
    parser.add_argument("--model-cache-path", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--output-path", type=Path)
    parser.add_argument(
        "--windowed", action="store_true", help="Average overlapping 128-token windows."
    )
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    results_root = data_root / "evaluation/results"
    dataset_path = (args.dataset_path or data_root / "evaluation/questions-v1.jsonl").resolve()
    evidence_path = (args.evidence_path or data_root / "evaluation/evidence-v1.jsonl").resolve()
    baseline_name = (
        "multilingual-structured-baseline-v1.json"
        if args.windowed
        else "contextual-structured-baseline-v1.json"
    )
    result_name = (
        "windowed-multilingual-baseline-v1.json"
        if args.windowed
        else "multilingual-structured-baseline-v1.json"
    )
    index_name = "windowed-multilingual-v1" if args.windowed else "multilingual-structured-v1"
    baseline_path = (args.baseline_path or results_root / baseline_name).resolve()
    output_path = (args.output_path or results_root / result_name).resolve()
    chroma_path = (args.chroma_path or data_root / "chroma" / index_name).resolve()
    cache_path = (args.model_cache_path or data_root / "models").resolve()
    source_paths = sorted((data_root / "samples").glob("*.cbl"))
    input_paths = [dataset_path, evidence_path, baseline_path, *source_paths]
    if output_path in input_paths:
        raise ValueError("output path must not overwrite evaluation inputs")

    cases = load_evaluation_cases(dataset_path)
    requirements = load_evidence_requirements(evidence_path, cases=cases, data_root=data_root)
    documents = {
        doc.source_path: doc for doc in load_cobol_files(source_paths, data_root=data_root)
    }
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_config = baseline["configuration"]
    if any(
        baseline_config[key] != expected
        for key, expected in {
            "model": MODEL_ID if args.windowed else "all-MiniLM-L6-v2",
            "distance": "cosine",
            "chunking": "cobol-structure-v1",
            "embedding_input": "source-path-symbol-text-v1",
        }.items()
    ):
        raise ValueError("comparison requires the original contextual baseline")
    if args.windowed and baseline_config["revision"] != MODEL_REVISION:
        raise ValueError("window comparison requires the same model revision")
    if args.windowed and "windowing" in baseline:
        raise ValueError("window comparison requires an unwindowed baseline")
    baseline_metrics = (
        baseline["multilingual_file_metrics"] if args.windowed else baseline["contextual_metrics"]
    )
    baseline_rankings = load_saved_rankings(baseline_path, cases=cases, documents=documents)
    baseline_evidence = evaluate_chunk_evidence(cases, requirements, baseline_rankings)

    model_dir = Path(
        snapshot_download(
            MODEL_ID,
            revision=MODEL_REVISION,
            allow_patterns=list(MODEL_FILES),
            cache_dir=str(cache_path),
            token=False,
            local_files_only=args.local_files_only,
            max_workers=2,
        )
    )
    encoder = (
        WindowedMultilingualOnnxEmbedding(model_dir)
        if args.windowed
        else MultilingualOnnxEmbedding(model_dir)
    )
    chunks = [chunk for doc in documents.values() for chunk in chunk_cobol_structure(doc)]
    if len(chunks) != baseline["chunk_count"]:
        raise ValueError("comparison requires unchanged chunking")
    answerable = [case for case in cases if case.answerable]
    document_lengths = encoder.token_lengths([build_contextual_embedding_text(c) for c in chunks])
    query_lengths = encoder.token_lengths([case.question for case in answerable])

    collection = chromadb.PersistentClient(path=str(chroma_path)).get_or_create_collection(
        name=f"legacy-rag-{index_name}",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    result = run_structured_baseline(
        data_root=data_root,
        dataset_path=dataset_path,
        collection=collection,
        embed_texts=encoder,
        embedding_text_builder=build_contextual_embedding_text,
        k=5,
    )
    evidence = evaluate_chunk_evidence(
        cases,
        requirements,
        {
            case_id: [EvidenceChunk(c.chunk_id, c.source_path, c.text) for c in ranked]
            for case_id, ranked in result.retrieved_chunks_by_case_id.items()
        },
    )
    file_metrics = metrics_from_report(result.report)
    output = {
        "configuration": {
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "model_file": "onnx/model.onnx",
            "provider": "CPUExecutionProvider",
            "pooling": "attention-masked-mean-l2",
            "max_length": encoder.max_length,
            "distance": "cosine",
            "chunking": "cobol-structure-v1",
            "embedding_input": "source-path-symbol-text-v1",
            "chroma_path": str(chroma_path),
            "versions": {
                name: version(name)
                for name in ("chromadb", "onnxruntime", "tokenizers", "numpy", "huggingface-hub")
            },
            "input_hashes": {str(p): file_hash(p) for p in input_paths},
            "model_hashes": {name: file_hash(model_dir / name) for name in MODEL_FILES},
        },
        "chunk_count": result.chunk_count,
        "truncation": {
            "document_count": sum(n > encoder.max_length for n in document_lengths),
            "query_count": sum(n > encoder.max_length for n in query_lengths),
            "document_token_lengths": dict(
                zip((c.chunk_id for c in chunks), document_lengths, strict=True)
            ),
            "query_token_lengths": dict(
                zip((c.id for c in answerable), query_lengths, strict=True)
            ),
        },
        "baseline_file_metrics": baseline_metrics,
        "multilingual_file_metrics": file_metrics,
        "file_metric_deltas": {
            key: value - baseline_metrics[key] for key, value in file_metrics.items()
        },
        "baseline_evidence": baseline_evidence,
        "multilingual_evidence": evidence,
        "report": asdict(result.report),
        "retrieved_chunks_by_case_id": {
            case_id: [{**asdict(chunk), "score": round(chunk.score, 6)} for chunk in ranked]
            for case_id, ranked in result.retrieved_chunks_by_case_id.items()
        },
    }
    if args.windowed:
        document_stats = encoder.window_statistics(
            [build_contextual_embedding_text(c) for c in chunks]
        )
        query_stats = encoder.window_statistics([case.question for case in answerable])
        if not all(item["complete"] for item in [*document_stats, *query_stats]):
            raise ValueError("windowing must preserve every payload token")
        output["input_lengths"] = output.pop("truncation")
        output["windowing"] = {
            "overlap": encoder.overlap,
            "aggregation": "equal-window-mean-l2",
            "document_windows": sum(item["window_count"] for item in document_stats),
            "query_windows": sum(item["window_count"] for item in query_stats),
            "documents": dict(zip((c.chunk_id for c in chunks), document_stats, strict=True)),
            "queries": dict(zip((c.id for c in answerable), query_stats, strict=True)),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"mrr={file_metrics['mrr']:.4f}")
    for k in (1, 3, 5, 10):
        print(f"evidence_complete@{k}={evidence['metrics'][str(k)]['evidence_complete']:.4f}")
    if args.windowed:
        print(
            f"document_windows={output['windowing']['document_windows']} for {len(chunks)} chunks"
        )
        print(
            f"query_windows={output['windowing']['query_windows']} for {len(answerable)} questions"
        )
    else:
        print(f"truncated_documents={output['truncation']['document_count']}/{len(chunks)}")
        print(f"truncated_queries={output['truncation']['query_count']}/{len(answerable)}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
