"""Score prepared public candidates with a local model; no downloads or generation."""
import argparse
import json
import math
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".metadata.json").exists():
        parser.error("output exists; choose a new filename")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    # The input contains questions and candidates only; no gold evidence or answers.
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    start = perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_dir, local_files_only=True, trust_remote_code=False,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_dir, local_files_only=True, trust_remote_code=False,
    ).to("cpu").eval()
    load_seconds = perf_counter() - start
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for case in data["cases"]:
            start = perf_counter()
            scores = []
            truncated = 0
            for offset in range(0, len(case["candidates"]), 4):
                group = case["candidates"][offset:offset + 4]
                pairs = [(case["question"], row["passage"]) for row in group]
                lengths = tokenizer(pairs, truncation=False, padding=False)["input_ids"]
                truncated += sum(len(ids) > 512 for ids in lengths)
                inputs = tokenizer(
                    pairs, padding=True, truncation=True, max_length=512, return_tensors="pt",
                )
                with torch.inference_mode():
                    values = model(**inputs, return_dict=True).logits.view(-1).float().tolist()
                assert len(values) == len(group) and all(math.isfinite(v) for v in values)
                scores.extend(values)
            ordered = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
            row = {
                "case_id": case["case_id"],
                "ranked_ids": [case["candidates"][i]["chunk_id"] for i in ordered],
                "scores": [scores[i] for i in ordered],
                "elapsed_seconds": perf_counter() - start,
                "truncated_pairs": truncated,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{case['case_id']}: {row['elapsed_seconds']:.3f}s", flush=True)
    metadata = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model": "BAAI/bge-reranker-v2-m3", "revision": args.model_dir.name,
        "device": "cpu", "threads": 4, "batch_size": 4, "max_length": 512,
        "load_seconds": load_seconds, "generation_calls": 0,
        "input_sha256": sha256(args.input.read_bytes()).hexdigest(),
        "output_sha256": sha256(args.output.read_bytes()).hexdigest(),
        "versions": {name: version(name) for name in ("torch", "transformers", "tokenizers")},
    }
    with args.output.with_suffix(".metadata.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
