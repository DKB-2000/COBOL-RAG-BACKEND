"""Fixed public 30-case evaluation. Default is preflight only: no generation calls."""
import argparse
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import httpx

from legacy_rag.api.public_corpus import load_public_chunks
from legacy_rag.evaluation.answer_metrics import summarize_generation
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import load_evidence_requirements
from legacy_rag.evaluation.generation_runner import collect_generation, make_review_template
from legacy_rag.generation.models import GeneratedAnswer
from legacy_rag.generation.prompt import SYSTEM_PROMPT, build_generation_request
from legacy_rag.retrieval.chroma_store import SearchResult
from legacy_rag.retrieval.context import assemble_context

PROJECT = Path(__file__).resolve().parents[1]
HERE = PROJECT / "artifacts"
DATA = PROJECT / "data"
DATASET = DATA / "evaluation/questions-v1.jsonl"
EVIDENCE = DATA / "evaluation/evidence-v1.jsonl"
RUBRIC = DATA / "evaluation/answer-rubric-v1.jsonl"
EXPECTED_DATASET_HASH = "1d07bb2d710a600610a17e318947394e380a5529f3a3d2b8c02a80113506987e"


def json_write(path, value, *, exclusive=True):
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def expected_context_ids(approved, profile, reranking):
    if reranking == "disabled":
        reference = json.loads((DATA / "evaluation/results/identifier-aware-retrieval-v1.json")
                               .read_text(encoding="utf-8"))
        return {key: row["context_ids"] for key, row in reference["profiles"][profile]["cases"].items()}
    if profile != "identifier-aware":
        raise ValueError("reranked evaluation requires identifier-aware; use disabled for original")
    reference = json.loads((DATA / "evaluation/results/reranker-int8-length-v1.json")
                           .read_text(encoding="utf-8"))
    return {row["case_id"]: [chunk.chunk_id for chunk in assemble_context(
        approved[key] for key in row["ranked_ids"])] for row in reference["rankings"]}


class HttpProbe:
    def __init__(self, client, approved, *, max_queries=0, journal=None, search_limit=10):
        self.client, self.approved = client, approved
        self.remaining, self.journal = max_queries, journal
        self.search_limit = search_limit

    def search(self, question):
        response = self.client.post("/search", json={"query": question, "limit": self.search_limit})
        response.raise_for_status()
        results = []
        for item in response.json()["results"]:
            chunk = self.approved.get(item["chunk_id"])
            if chunk is None or any(item[key] != getattr(chunk, key) for key in
                                    ("text", "source_path", "symbol", "language", "chunk_index")):
                raise ValueError("search result outside the frozen public corpus")
            results.append(SearchResult(**asdict(chunk), score=item["score"]))
        return results

    def __call__(self, question):
        started = perf_counter()
        try:
            retrieved = self.search(question)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"error_kind": "search_or_public_corpus_error", "api_query_attempted": False}
        context = assemble_context(retrieved)
        observation = {
            "retrieved_chunks": [asdict(chunk) for chunk in retrieved],
            "reconstructed_context": [asdict(chunk) for chunk in context],
            "context_capture_mode": "reconstructed_from_separate_search_request",
            "actual_model_prompt_observed": False,
            "search_elapsed_seconds": round(perf_counter() - started, 6),
            "api_query_attempted": False,
        }
        if self.remaining <= 0:
            return {**observation, "error_kind": "query_budget_exhausted"}
        self.remaining -= 1
        # Persist intent before sending; a timeout must never trigger an automatic retry.
        if self.journal is not None:
            self.journal.write(json.dumps({
                "question": question, "timestamp_utc": datetime.now(UTC).isoformat(),
                "event": "query_about_to_send",
            }, ensure_ascii=False) + "\n")
            self.journal.flush()
        observation["api_query_attempted"] = True
        started = perf_counter()
        try:
            response = self.client.post("/query", json={"query": question, "limit": 10})
            observation["http_status"] = response.status_code
            if response.status_code != 200:
                observation["error_kind"] = "query_http_error"
            else:
                observation["response"] = response.json()
        except httpx.TimeoutException:
            observation["error_kind"] = "query_http_timeout_no_retry"
        except (httpx.HTTPError, ValueError):
            observation["error_kind"] = "query_transport_or_decode_error"
        observation["query_elapsed_seconds"] = round(perf_counter() - started, 6)
        return observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Paid: at most 30 /query calls")
    mode.add_argument("--score", type=Path, metavar="REVIEW_JSONL", help="Offline judgments only")
    parser.add_argument("--prefix", default="generation-v1")
    parser.add_argument("--retrieval-profile", choices=("original", "identifier-aware"),
                        default="identifier-aware", help="Expected server profile; does not configure it")
    parser.add_argument("--reranking", choices=("bge-int8", "disabled"), default="bge-int8",
                        help="Expected server reranking; use disabled for historical baselines")
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9-]+", args.prefix) is None:
        raise ValueError("prefix must be a filename, not a directory")
    HERE.mkdir(exist_ok=True)

    def target(suffix):
        return HERE / f"{args.prefix}-{suffix}"
    if args.score is not None:
        records = [json.loads(line) for line in target("responses.jsonl").read_text(
            encoding="utf-8").splitlines()]
        reviews = [json.loads(line) for line in args.score.read_text(encoding="utf-8").splitlines()]
        summary = summarize_generation(records, reviews)
        name = "score-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
        json_write(target(name), summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.execute and any(target(suffix).exists() for suffix in (
        "manifest.json", "attempts.jsonl", "responses.jsonl", "reviews-template.jsonl",
        "summary-unreviewed.json",
    )):
        raise FileExistsError("run output already exists; do not repeat paid calls")
    if sha256(DATASET.read_bytes()).hexdigest() != EXPECTED_DATASET_HASH:
        raise ValueError("only the original public questions-v1 dataset is permitted")
    cases = load_evaluation_cases(DATASET)
    if len(cases) != 30 or sum(case.answerable for case in cases) != 24:
        raise ValueError("fixed evaluation must contain 24 answerable and 6 unanswerable cases")
    approved = load_public_chunks(DATA)
    if len(approved) != 52:
        raise ValueError("the original public corpus changed or is incomplete")
    expected_contexts = expected_context_ids(approved, args.retrieval_profile, args.reranking)
    search_limit = 30 if args.reranking == "bge-int8" else 10
    load_evidence_requirements(EVIDENCE, cases=cases, data_root=DATA)
    rubric_records = [json.loads(line) for line in RUBRIC.read_text(encoding="utf-8").splitlines()]
    rubric = {record["case_id"]: record["required_points"] for record in rubric_records}
    if len(rubric_records) != 30 or set(rubric) != {case.id for case in cases}:
        raise ValueError("rubric must cover all 30 cases exactly once")
    source_paths = sorted({DATA / chunk.source_path for chunk in approved.values()})
    input_paths = [DATASET, EVIDENCE, RUBRIC, *source_paths]
    input_hashes = {str(path.relative_to(PROJECT)): sha256(path.read_bytes()).hexdigest()
                    for path in input_paths}
    with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False,
                      timeout=httpx.Timeout(300, connect=5)) as client:
        client.get("/health").raise_for_status()
        probe = HttpProbe(client, approved, search_limit=search_limit)
        preflight = []
        for case in cases:
            context = assemble_context(probe.search(case.question))
            request = build_generation_request(case.question, context)
            preflight.append({
                "case_id": case.id, "context_ids": [chunk.chunk_id for chunk in context],
                "raw_context_characters": sum(len(chunk.text) for chunk in context),
                "prompt_utf8_bytes": len((request.system_prompt + request.user_prompt).encode()),
            })
        manifest = {
            "schema_version": "generation-evaluation-v1", "cases": 30,
            "answerable": 24, "unanswerable": 6, "model_expected": "gpt-6-luna",
            "actual_provider_model_observed": None, "max_query_calls": 30,
            "retrieval_profile_expected": args.retrieval_profile,
            "reranking_expected": args.reranking, "preflight_search_limit": search_limit,
            "sdk_retries_expected": 0, "max_output_tokens_expected": 1000,
            "input_hashes": input_hashes, "preflight": preflight,
            "packages": {name: version(name) for name in ("openai", "httpx", "pydantic")},
            "schema_sha256": sha256(json.dumps(GeneratedAnswer.model_json_schema(),
                                               sort_keys=True).encode()).hexdigest(),
            "system_prompt_sha256": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            "code_hashes": {
                str(path.relative_to(PROJECT)): sha256(path.read_bytes()).hexdigest()
                for path in [Path(__file__).resolve(), *sorted(
                    (PROJECT / "src/legacy_rag/generation").glob("*.py")),
                    PROJECT / "src/legacy_rag/api/dependencies.py",
                    PROJECT / "src/legacy_rag/api/public_corpus.py",
                    PROJECT / "src/legacy_rag/retrieval/context.py"]
            },
            "measurement": "sequential HTTP /query; separate local /search before each case",
            "actual_token_usage": None, "actual_cost_usd": None,
            "cost_estimate_usd": {"typical_4000_input_1000_output_tokens_each": 0.027,
                                  "not_a_hard_spend_limit": True},
        }
        mismatches = [row["case_id"] for row in preflight
                      if row["context_ids"] != expected_contexts[row["case_id"]]]
        manifest["profile_context_mismatch_cases"] = mismatches
        if mismatches:
            json_write(target("preflight.json"), manifest, exclusive=False)
            raise ValueError("server retrieval differs from selected profile; no generation calls sent")
        if not args.execute:
            json_write(target("preflight.json"), manifest, exclusive=False)
            print(f"preflight_ok: cases=30 context_cases={len(preflight)} paid_calls=0")
            print(f"output={target('preflight.json')}")
            return
        # Exclusive files prevent accidental reruns of a paid experiment.
        json_write(target("manifest.json"), manifest)
        with target("attempts.jsonl").open("x", encoding="utf-8") as journal, \
                target("responses.jsonl").open("x", encoding="utf-8") as output:
            probe = HttpProbe(client, approved, max_queries=30, journal=journal,
                              search_limit=search_limit)

            def persist(record):
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                print(record["case_id"], record["status"],
                      record.get("query_elapsed_seconds"), flush=True)

            records = collect_generation(cases, probe, on_result=persist)
        with target("reviews-template.jsonl").open("x", encoding="utf-8") as output:
            for review in make_review_template(records, rubric):
                output.write(json.dumps(review, ensure_ascii=False) + "\n")
        json_write(target("summary-unreviewed.json"), summarize_generation(records))
        if any(sha256((PROJECT / path).read_bytes()).hexdigest() != digest
               for path, digest in input_hashes.items()):
            raise ValueError("evaluation inputs changed during the run")
        print("completed: review semantic correctness before publishing quality rates")


if __name__ == "__main__":
    main()
