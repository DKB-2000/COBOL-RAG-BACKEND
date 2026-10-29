"""Verify actual API retrieval with a recording generation stub; no LLM calls.

Default: validate fixed inputs only. --execute starts an isolated loopback API,
indexes public sources, and observes the actual model prompt for both profiles.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from math import ceil
from pathlib import Path
from time import perf_counter, sleep

import httpx
from evaluate_generation import DATA, HERE, PROJECT, expected_context_ids, json_write
from evaluate_ollama import idle_sleep_guard

from legacy_rag.api import dependencies
from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES, load_public_chunks
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.evidence import evaluate_chunk_evidence, load_evidence_requirements
from legacy_rag.generation.models import GeneratedAnswer
from legacy_rag.main import create_app


def create_verification_app():
    if dependencies.ApiSettings().generation_provider != "disabled":
        raise ValueError("verification forbids generation providers")
    trace = Path(os.environ["LEGACY_RAG_VERIFICATION_TRACE"])

    class RecordingStub:
        metadata = None

        def generate(self, request):
            payload = json.loads(request.user_prompt)
            if self.metadata is None and dependencies.ApiSettings().reranking == "bge-int8":
                import torch
                owner = dependencies._get_reranker()
                self.metadata = {
                    "torch": torch.__version__, "threads": torch.get_num_threads(),
                    "quantized_engine": torch.backends.quantized.engine,
                    "quantized_linear_modules": sum(isinstance(
                        module, torch.ao.nn.quantized.dynamic.Linear)
                        for module in owner._model.modules()),
                    "model_owners_cached": dependencies._get_reranker.cache_info().currsize,
                }
            with trace.open("a", encoding="utf-8") as output:
                output.write(json.dumps({**payload, "runtime": self.metadata},
                                        ensure_ascii=False) + "\n")
            return GeneratedAnswer(status="refused", reason="insufficient_evidence")

    app = create_app()
    stub = RecordingStub()
    app.dependency_overrides[dependencies.get_generation_model] = lambda: stub
    return app


def verify_context(case, payload, approved, expected):
    if payload["question"] != case.question:
        raise ValueError("recorded question differs")
    selected = []
    for row in payload["context"]:
        chunk = approved.get(row["chunk_id"])
        if chunk is None or any(row[key] != getattr(chunk, key)
                                for key in ("source_path", "symbol", "text")):
            raise ValueError("recorded context outside the frozen public corpus")
        selected.append(chunk)
    if [chunk.chunk_id for chunk in selected] != expected:
        raise ValueError(f"actual API context mismatch: {case.id}")
    return selected


def run_profile(mode, target, cases, approved, requirements):
    trace = target(f"{mode}-prompts.jsonl")
    trace.touch(exist_ok=False)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("LEGACY_RAG_") and key not in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}}
    env.update({
        "LEGACY_RAG_GENERATION_PROVIDER": "disabled", "LEGACY_RAG_DATA_ROOT": str(DATA),
        "LEGACY_RAG_CHROMA_PATH": str(target("chroma")),
        "LEGACY_RAG_VERIFICATION_TRACE": str(trace),
        "LEGACY_RAG_RETRIEVAL_PROFILE": "identifier-aware", "PYTHONUTF8": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    })
    # The enabled run intentionally exercises the production default.
    if mode == "disabled":
        env["LEGACY_RAG_RERANKING"] = mode
    with target(f"{mode}-server.log").open("x", encoding="utf-8") as server_log:
        process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "verify_reranking_api:create_verification_app",
            "--factory", "--app-dir", str(PROJECT / "scripts"), "--host", "127.0.0.1",
            "--port", "8013", "--no-access-log",
        ], cwd=PROJECT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(base_url="http://127.0.0.1:8013", trust_env=False,
                              timeout=httpx.Timeout(300, connect=5)) as client:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError("isolated API exited; inspect its log")
                    try:
                        if client.get("/health", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    sleep(1)
                else:
                    raise RuntimeError("isolated API did not start")
                if mode == "disabled":
                    index = client.post("/documents/index", json={
                        "source_paths": sorted(PUBLIC_SOURCE_HASHES), "rebuild": True,
                    })
                    index.raise_for_status()
                    if index.json() != {"indexed_documents": 5, "indexed_chunks": 52}:
                        raise ValueError("unexpected public index")
                started = perf_counter()
                ready = client.get("/ready")
                ready.raise_for_status()
                cold_ready = round(perf_counter() - started, 6)
                print(mode, "cold_ready_seconds", cold_ready, flush=True)
                # Preserve the actual /search contract, including original cosine scores.
                search = client.post("/search", json={"query": cases[0].question, "limit": 30})
                search.raise_for_status()
                json_write(target(f"{mode}-search.json"), search.json())
                expected = expected_context_ids(approved, "identifier-aware", mode)
                selected, observations = {}, []
                with target(f"{mode}-requests.jsonl").open("x", encoding="utf-8") as output:
                    for case in cases:
                        timestamp = datetime.now(UTC).isoformat()
                        started = perf_counter()
                        response = client.post("/query", json={"query": case.question, "limit": 10})
                        elapsed = round(perf_counter() - started, 6)
                        row = {"case_id": case.id, "started_at_utc": timestamp,
                               "http_status": response.status_code, "elapsed_seconds": elapsed}
                        output.write(json.dumps(row) + "\n")
                        output.flush()
                        response.raise_for_status()
                        # Stub refusal is a trace mechanism, never a refusal-quality result.
                        if response.json()["status"] != "refused":
                            raise ValueError("recording stub was not used")
                        prompts = [json.loads(line) for line in trace.read_text(
                            encoding="utf-8").splitlines()]
                        if len(prompts) != len(observations) + 1:
                            raise ValueError("expected exactly one recorded prompt per query")
                        selected[case.id] = verify_context(case, prompts[-1], approved, expected[case.id])
                        row["context_ids"] = [chunk.chunk_id for chunk in selected[case.id]]
                        observations.append(row)
                        print(mode, case.id, elapsed, "context_match", flush=True)
                        if elapsed > 390:
                            raise RuntimeError("execution gap; preserve raw output and stop")
                evidence = evaluate_chunk_evidence(cases, requirements, selected, ks=(10,))
                complete = sorted(row["case_id"] for row in evidence["case_results"]
                                  if row["by_k"]["10"]["evidence_complete"] == 1)
                times = sorted(row["elapsed_seconds"] for row in observations)
                return {
                    "complete_cases": complete, "evidence_count": len(complete),
                    "context_matches": len(observations), "cold_ready_seconds": cold_ready,
                    "cold_ready_scope": "one /ready including search and, when enabled, model load/INT8 conversion/ranking",
                    "warm_http_seconds": {"n": len(times), "p50": times[ceil(len(times) * .5) - 1],
                                          "p95": times[ceil(len(times) * .95) - 1]},
                    "runtime": prompts[-1]["runtime"], "observations": observations,
                    "evidence": evidence,
                }
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prefix", default="reranker-api-v1")
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9-]+", args.prefix) is None:
        raise ValueError("prefix must be a filename")
    cases = load_evaluation_cases(DATA / "evaluation/questions-v1.jsonl")
    approved = load_public_chunks(DATA)
    reference = json.loads((DATA / "evaluation/results/reranker-int8-length-v1.json")
                           .read_text(encoding="utf-8"))
    if len(cases) != 30 or sum(case.answerable for case in cases) != 24 or len(approved) != 52:
        raise ValueError("fixed public corpus/cases changed")
    for path, digest in reference["input_hashes"].items():
        if sha256((PROJECT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("frozen input hash mismatch")
    requirements = load_evidence_requirements(
        DATA / "evaluation/evidence-v1.jsonl", cases=cases, data_root=DATA)
    for mode in ("disabled", "bge-int8"):
        if set(expected_context_ids(approved, "identifier-aware", mode)) != {case.id for case in cases}:
            raise ValueError("reference contexts incomplete")
    if not args.execute:
        print("preflight_inputs_ok: 30 cases, 52 public chunks; generation_calls=0")
        return
    with socket.socket() as port_check:
        port_check.bind(("127.0.0.1", 8013))
    HERE.mkdir(exist_ok=True)

    def target(suffix):
        return HERE / f"{args.prefix}-{suffix}"

    json_write(target("reserved.json"), {"created_at_utc": datetime.now(UTC).isoformat()})
    profiles = {}
    for mode in ("disabled", "bge-int8"):
        profiles[mode] = run_profile(mode, target, cases, approved, requirements)
        json_write(target(f"{mode}-summary.json"), profiles[mode])
    before, after = (set(profiles[key]["complete_cases"]) for key in ("disabled", "bge-int8"))
    if before != set(reference["before_complete"]) or after != set(reference["after_complete"]):
        raise ValueError("actual API evidence differs from the saved INT8 experiment")
    searches = {mode: json.loads(target(f"{mode}-search.json").read_text(encoding="utf-8"))["results"]
                for mode in profiles}
    expected_rank = next(row["ranked_ids"] for row in reference["rankings"]
                         if row["case_id"] == cases[0].id)
    if [row["chunk_id"] for row in searches["bge-int8"]] != expected_rank:
        raise ValueError("actual /search ranking differs")
    vector_scores = {row["chunk_id"]: row["score"] for row in searches["disabled"]}
    if any(row["score"] != vector_scores[row["chunk_id"]] for row in searches["bge-int8"]):
        raise ValueError("original vector scores changed")
    for path, digest in reference["input_hashes"].items():
        if sha256((PROJECT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("inputs changed during verification")
    result = {
        "schema_version": "reranker-api-verification-v1",
        "created_at_utc": datetime.now(UTC).isoformat(), "generation_calls": 0,
        "recording_stub_calls": 60, "profiles": profiles, "denominator": 24,
        "before_count": len(before), "after_count": len(after),
        "improved": sorted(after - before), "regressed": sorted(before - after),
        "input_hashes": reference["input_hashes"],
        "packages": {key: version(key) for key in ("torch", "transformers", "tokenizers", "sentencepiece")},
        "measurement_scope": "sequential actual HTTP /query retrieval/context with recording stub; no LLM inference",
        "percentile_method": "nearest_rank", "search_rank_matches": True,
        "original_vector_scores_preserved": True, "production_default_exercised": True,
        "limitations": ["Development set, not holdout or answer accuracy.",
                        "No generation/refusal quality measurement or production redeploy.",
                        "Single CPU host, sequential 30 cases per profile; cold readiness n=1."],
    }
    json_write(target("result.json"), result)
    print(f"verified actual API evidence: {len(before)} -> {len(after)}/24; generation_calls=0", flush=True)


if __name__ == "__main__":
    if "--execute" in sys.argv:
        with idle_sleep_guard():
            main()
    else:
        main()
