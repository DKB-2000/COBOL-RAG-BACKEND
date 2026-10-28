"""Prepare public query/candidate pairs without exposing evaluation labels to the reranker."""
import argparse
import json
from hashlib import sha256
from pathlib import Path

from legacy_rag.api.public_corpus import load_public_chunks
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.structured_baseline import build_contextual_embedding_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new filename")
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    report = json.loads((data / "evaluation/results/retrieval-candidates-v1.json").read_text(
        encoding="utf-8",
    ))
    for path, digest in report["input_hashes"].items():
        assert sha256((root / path).read_bytes()).hexdigest() == digest
    chunks = load_public_chunks(data)
    cases = load_evaluation_cases(data / "evaluation/questions-v1.jsonl")
    output = {"cases": [
        {"case_id": case.id, "question": case.question, "candidates": [
            {"chunk_id": chunk_id, "passage": build_contextual_embedding_text(chunks[chunk_id])}
            for chunk_id in report["metrics"]["30"]["candidate_ids"][case.id]
        ]} for case in cases
    ]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
