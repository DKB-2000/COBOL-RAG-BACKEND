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
    parser.add_argument("--precision", choices=("fp32", "dynamic-int8"), default="fp32")
    parser.add_argument("--case", action="append", help="Restrict a pilot to these case IDs")
    parser.add_argument("--batch-order", choices=("retrieval", "length"), default="retrieval")
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".metadata.json").exists():
        parser.error("output exists; choose a new filename")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if args.case:
        known = {case["case_id"] for case in data["cases"]}
        if not set(args.case) <= known:
            parser.error("unknown case ID")
        data["cases"] = [case for case in data["cases"] if case["case_id"] in args.case]
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
    quantization_seconds = 0.0
    quantized_linear_count = 0
    if args.precision == "dynamic-int8":
        start = perf_counter()
        model = torch.ao.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8, inplace=False,
        )
        quantization_seconds = perf_counter() - start
        quantized_linear_count = sum(
            isinstance(module, torch.ao.nn.quantized.dynamic.Linear)
            for module in model.modules()
        )
        if quantized_linear_count == 0:
            raise RuntimeError("No Linear modules were quantized")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for case in data["cases"]:
            start = perf_counter()
            scores = [0.0] * len(case["candidates"])
            truncated = 0
            batch_indices = list(range(len(case["candidates"])))
            if args.batch_order == "length":
                pairs = [(case["question"], row["passage"]) for row in case["candidates"]]
                lengths = tokenizer(pairs, truncation=False, padding=False)["input_ids"]
                batch_indices.sort(key=lambda index: len(lengths[index]))
            padded_tokens = 0
            for offset in range(0, len(batch_indices), 4):
                indices = batch_indices[offset:offset + 4]
                group = [case["candidates"][index] for index in indices]
                pairs = [(case["question"], row["passage"]) for row in group]
                lengths = tokenizer(pairs, truncation=False, padding=False)["input_ids"]
                truncated += sum(len(ids) > 512 for ids in lengths)
                inputs = tokenizer(
                    pairs, padding=True, truncation=True, max_length=512, return_tensors="pt",
                )
                padded_tokens += inputs["input_ids"].numel()
                with torch.inference_mode():
                    values = model(**inputs, return_dict=True).logits.view(-1).float().tolist()
                assert len(values) == len(group) and all(math.isfinite(v) for v in values)
                for index, value in zip(indices, values, strict=True):
                    scores[index] = value
            ordered = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
            row = {
                "case_id": case["case_id"],
                "ranked_ids": [case["candidates"][i]["chunk_id"] for i in ordered],
                "scores": [scores[i] for i in ordered],
                "elapsed_seconds": perf_counter() - start,
                "truncated_pairs": truncated,
                "padded_tokens": padded_tokens,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{case['case_id']}: {row['elapsed_seconds']:.3f}s", flush=True)
    metadata = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model": "BAAI/bge-reranker-v2-m3", "revision": args.model_dir.name,
        "device": "cpu", "threads": 4, "batch_size": 4, "max_length": 512,
        "precision": args.precision, "quantized_linear_count": quantized_linear_count,
        "batch_order": args.batch_order,
        "quantization_engine": torch.backends.quantized.engine,
        "quantization_seconds": quantization_seconds,
        "case_ids": [case["case_id"] for case in data["cases"]],
        "load_seconds": load_seconds, "generation_calls": 0,
        "input_sha256": sha256(args.input.read_bytes()).hexdigest(),
        "output_sha256": sha256(args.output.read_bytes()).hexdigest(),
        "versions": {name: version(name) for name in ("torch", "transformers", "tokenizers")},
    }
    with args.output.with_suffix(".metadata.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
