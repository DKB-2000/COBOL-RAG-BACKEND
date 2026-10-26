import argparse
import json
from hashlib import sha256
from pathlib import Path

from legacy_rag.evaluation.dataset import EvaluationCase, load_evaluation_cases
from legacy_rag.evaluation.evidence import (
    EvidenceChunk,
    evaluate_chunk_evidence,
    load_evidence_requirements,
)
from legacy_rag.ingestion.chunker import chunk_document
from legacy_rag.ingestion.loader import load_cobol_files
from legacy_rag.ingestion.models import SourceDocument


def load_saved_rankings(
    path: Path,
    *,
    cases: list[EvaluationCase],
    documents: dict[str, SourceDocument],
) -> dict[str, list[EvidenceChunk]]:
    saved = json.loads(path.read_text(encoding="utf-8"))
    answerable = {case.id: case for case in cases if case.answerable}
    records = saved["report"]["case_results"]
    if len(records) != len(answerable) or {r["case_id"] for r in records} != set(answerable):
        raise ValueError("baseline must cover the same answerable cases")
    for record in records:
        case = answerable[record["case_id"]]
        if (
            record["question"] != case.question
            or tuple(record["expected_sources"]) != case.expected_sources
        ):
            raise ValueError(f"baseline dataset mismatch: {case.id}")

    if "retrieved_chunks_by_case_id" not in saved:
        rankings = {}
        for record in records:
            chunks = [
                chunk_document(documents[source])[0] for source in record["retrieved_sources"]
            ]
            if len(chunks) != len(documents) or len({c.source_path for c in chunks}) != len(
                documents
            ):
                raise ValueError(
                    "file baseline must preserve every ranked source for top-10 comparison"
                )
            rankings[record["case_id"]] = [
                EvidenceChunk(c.chunk_id, c.source_path, c.text) for c in chunks
            ]
        return rankings

    rankings = {}
    for case_id in answerable:
        records = saved["retrieved_chunks_by_case_id"][case_id]
        if len(records) < min(10, saved["chunk_count"]):
            raise ValueError(f"baseline does not preserve enough ranked chunks: {case_id}")
        for record in records:
            source = documents[record["source_path"]]
            if record["content_hash"] != source.content_hash or record["text"] not in source.text:
                raise ValueError(f"baseline source content mismatch: {case_id}")
        rankings[case_id] = [
            EvidenceChunk(record["chunk_id"], record["source_path"], record["text"])
            for record in records
        ]
    return rankings


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Evaluate code evidence in saved top-ranked chunks."
    )
    parser.add_argument("--data-root", type=Path, default=project_root / "data")
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument("--file-baseline-path", type=Path)
    parser.add_argument("--structured-baseline-path", type=Path)
    parser.add_argument("--contextual-baseline-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    dataset_path = (args.dataset_path or data_root / "evaluation" / "questions-v1.jsonl").resolve()
    evidence_path = (args.evidence_path or data_root / "evaluation" / "evidence-v1.jsonl").resolve()
    results_root = data_root / "evaluation" / "results"
    baseline_paths = {
        "file_level": (
            args.file_baseline_path or results_root / "file-level-baseline-v1.json"
        ).resolve(),
        "structured": (
            args.structured_baseline_path or results_root / "structured-baseline-v1.json"
        ).resolve(),
        "contextual": (
            args.contextual_baseline_path or results_root / "contextual-structured-baseline-v1.json"
        ).resolve(),
    }
    output_path = (args.output_path or results_root / "chunk-evidence-v1.json").resolve()
    input_paths = [dataset_path, evidence_path, *baseline_paths.values()]
    source_paths = sorted((data_root / "samples").glob("*.cbl"))
    if output_path in [*input_paths, *source_paths]:
        raise ValueError("output path must not overwrite evaluation inputs")

    cases = load_evaluation_cases(dataset_path)
    requirements = load_evidence_requirements(evidence_path, cases=cases, data_root=data_root)
    documents = {
        doc.source_path: doc for doc in load_cobol_files(source_paths, data_root=data_root)
    }
    reports = {
        name: evaluate_chunk_evidence(
            cases,
            requirements,
            load_saved_rankings(path, cases=cases, documents=documents),
        )
        for name, path in baseline_paths.items()
    }
    output = {
        "configuration": {
            "ranking_unit": "chunk",
            "ks": [1, 3, 5, 10],
            "matching": "same-source-all-normalized-anchors-in-one-chunk-v1",
            "inputs": {
                str(path): sha256(path.read_bytes()).hexdigest()
                for path in [*input_paths, *source_paths]
            },
        },
        "reports": reports,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, report in reports.items():
        metrics = report["metrics"]["5"]
        misses = [
            case["case_id"]
            for case in report["case_results"]
            if case["by_k"]["5"]["source_hit"] and not case["by_k"]["5"]["evidence_complete"]
        ]
        print(
            f"{name}: symbol_coverage@5={metrics['symbol_coverage']:.4f} "
            f"evidence_complete@5={metrics['evidence_complete']:.4f} "
            f"mean_context_characters@5={metrics['context_characters']:.1f}"
        )
        print(f"source_hit_but_missing_evidence@5={','.join(misses) or 'none'}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
