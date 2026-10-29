"""Compare generation on frozen BGE contexts. Default is offline preflight only.

--execute runs an isolated actual API. OpenAI mode makes paid requests and
requires separate task approval. Each provider/question may be attempted once.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from time import perf_counter, sleep

import httpx
from evaluate_generation import expected_context_ids, json_write
from evaluate_ollama import idle_sleep_guard, read_lines

from legacy_rag.api.dependencies import ApiSettings, get_generation_model
from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES, load_public_chunks
from legacy_rag.evaluation.answer_metrics import summarize_generation
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.generation_runner import collect_generation, make_review_template
from legacy_rag.generation.ollama_model import OllamaGenerationModel
from legacy_rag.generation.openai_model import OpenAIGenerationModel
from legacy_rag.generation.prompt import SYSTEM_PROMPT, build_generation_request
from legacy_rag.main import create_app

PROJECT = Path(__file__).resolve().parents[1]
DATA, HERE = PROJECT / "data", PROJECT / "artifacts"
RUN_GROUP = "bge-generation-v1"


def load_inputs():
    cases = load_evaluation_cases(DATA / "evaluation/questions-v1.jsonl")
    approved = load_public_chunks(DATA)
    reference = json.loads((DATA / "evaluation/results/reranker-api-verification-v1.json")
                           .read_text(encoding="utf-8"))
    if len(cases) != 30 or sum(case.answerable for case in cases) != 24 or len(approved) != 52:
        raise ValueError("frozen public evaluation changed")
    for name, digest in {**reference["input_hashes"], **reference["code_hashes"]}.items():
        if sha256((PROJECT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("verified BGE pipeline or inputs changed")
    ids = expected_context_ids(approved, "identifier-aware", "bge-int8")
    expected = {case.question: asdict(build_generation_request(
        case.question, tuple(approved[key] for key in ids[case.id]))) for case in cases}
    return cases, approved, reference, expected


def validate_request(request, expected):
    payload = json.loads(request.user_prompt)
    if asdict(request) != expected.get(payload.get("question")):
        raise ValueError("actual model prompt differs from frozen BGE context")
    return payload


def remaining_cases(cases, calls):
    questions = {case.question for case in cases}
    attempted = [row["question"] for row in calls]
    if len(attempted) > 30 or len(set(attempted)) != len(attempted) or not set(attempted) <= questions:
        raise ValueError("ambiguous provider call ledger")
    return [case for case in cases if case.question not in set(attempted)]


def create_evaluation_app():
    provider = ApiSettings().generation_provider
    if provider not in {"openai", "ollama"} or ApiSettings().reranking != "bge-int8":
        raise ValueError("evaluation requires a generation provider and BGE")
    cases, _, _, expected = load_inputs()
    trace = Path(os.environ["LEGACY_RAG_EVALUATION_TRACE"])
    ledger = Path(os.environ["LEGACY_RAG_EVALUATION_LEDGER"])
    observed, lock = {}, Lock()

    def capture(response):
        response.read()
        observed["http_status"] = response.status_code
        try:
            observed["provider_response"] = response.json()
        except ValueError:
            observed["provider_decode_error"] = True

    if provider == "ollama":
        client = httpx.Client(
            base_url="http://127.0.0.1:11434", trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(300, connect=5), event_hooks={"response": [capture]},
        )
        adapter = OllamaGenerationModel(client=client, max_output_tokens=1024)
    else:
        from openai import DefaultHttpxClient, OpenAI
        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"], base_url="https://api.openai.com/v1",
            max_retries=0, timeout=httpx.Timeout(30, connect=5),
            http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False,
                                          event_hooks={"response": [capture]}),
        )
        adapter = OpenAIGenerationModel(client=client, model="gpt-6-luna", max_output_tokens=1000)

    class ObservedModel:
        def generate(self, request):
            with lock:
                payload = validate_request(request, expected)
                if payload["question"] not in {case.question for case in remaining_cases(cases, read_lines(ledger))}:
                    raise ValueError("provider question already attempted; no retry allowed")
                observed.clear()
                observed.update({"request": asdict(request), "provider": provider})
                with ledger.open("a", encoding="utf-8") as output:
                    output.write(json.dumps({"question": payload["question"],
                        "timestamp_utc": datetime.now(UTC).isoformat(),
                        "event": "provider_call_about_to_start"}, ensure_ascii=False) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                started = perf_counter()
                try:
                    answer = adapter.generate(request)
                    observed["parsed_answer"] = answer.model_dump()
                    return answer
                except Exception as error:
                    observed["adapter_error_kind"] = type(error).__name__
                    raise
                finally:
                    observed["generation_elapsed_seconds"] = round(perf_counter() - started, 6)
                    with trace.open("a", encoding="utf-8") as output:
                        output.write(json.dumps(observed, ensure_ascii=False) + "\n")

    app = create_app()
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original(app):
                yield
        finally:
            adapter.close()

    app.router.lifespan_context = lifespan
    model = ObservedModel()
    app.dependency_overrides[get_generation_model] = lambda: model
    return app


def openai_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
                key = winreg.QueryValueEx(registry, "OPENAI_API_KEY")[0].strip()
        except FileNotFoundError:
            pass
    if not key:
        raise ValueError("OPENAI_API_KEY is not configured; no requests sent")
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("ollama", "openai"), required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prefix")
    parser.add_argument("--resume-from", help="Collect only questions without a prior provider attempt")
    args = parser.parse_args()
    prefix = args.prefix or f"{RUN_GROUP}-{args.provider}"
    if any(re.fullmatch(r"[a-z0-9-]+", value) is None for value in (prefix, args.resume_from or "none")):
        raise ValueError("prefix must be a filename")
    cases, approved, reference, _ = load_inputs()
    if not args.execute:
        print(f"preflight_inputs_ok: 30 frozen BGE contexts; provider={args.provider}; generation_calls=0")
        return
    key = openai_key() if args.provider == "openai" else None
    with socket.socket() as check:
        check.bind(("127.0.0.1", 8014))
    HERE.mkdir(exist_ok=True)
    ledger = HERE / f"{RUN_GROUP}-{args.provider}-calls.jsonl"
    if args.resume_from:
        previous = json.loads((HERE / f"{args.resume_from}-manifest.json").read_text(encoding="utf-8"))
        if previous["provider"] != args.provider or previous["ledger"] != ledger.name:
            raise ValueError("resume provider/ledger differs")
        selected = remaining_cases(cases, read_lines(ledger))
    else:
        selected = cases
    if not selected:
        raise ValueError("no unattempted questions; do not repeat generation")

    def target(suffix):
        return HERE / f"{prefix}-{suffix}"

    json_write(target("reserved.json"), {"created_at_utc": datetime.now(UTC).isoformat()})
    if not args.resume_from:
        ledger.touch(exist_ok=False)
    target("provider-trace.jsonl").touch(exist_ok=False)
    env = {name: value for name, value in os.environ.items()
           if not name.startswith("LEGACY_RAG_") and name not in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}}
    env.update({
        "LEGACY_RAG_GENERATION_PROVIDER": args.provider, "LEGACY_RAG_RERANKING": "bge-int8",
        "LEGACY_RAG_RETRIEVAL_PROFILE": "identifier-aware", "LEGACY_RAG_DATA_ROOT": str(DATA),
        "LEGACY_RAG_CHROMA_PATH": str(target("chroma")),
        "LEGACY_RAG_EVALUATION_TRACE": str(target("provider-trace.jsonl")),
        "LEGACY_RAG_EVALUATION_LEDGER": str(ledger), "PYTHONUTF8": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    })
    if key:
        env["OPENAI_API_KEY"] = key
    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(), "provider": args.provider,
        "model_expected": "gpt-6-luna" if key else "qwen3:4b", "reranking": "bge-int8",
        "cases": len(selected), "selected_case_ids": [case.id for case in selected],
        "resume_from": args.resume_from, "ledger": ledger.name, "max_provider_calls_total": 30,
        "retries": 0, "input_hashes": reference["input_hashes"],
        "code_hashes": {name: sha256((PROJECT / name).read_bytes()).hexdigest() for name in (
            "scripts/evaluate_reranked_generation.py", "src/legacy_rag/generation/ollama_model.py",
            "src/legacy_rag/generation/openai_model.py", "src/legacy_rag/api/dependencies.py",
            "src/legacy_rag/retrieval/reranking.py")},
        "system_prompt_sha256": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "prompt_validation": "exact question/system/context text and order before each provider call",
        "measurement": "actual sequential HTTP /query including BGE retrieval and generation",
        "output_limit": 1000 if key else 1024,
        "ollama_options": None if key else {"num_ctx": 8192, "think": False, "keep_alive": 0},
    }
    if not key:
        manifest["ollama_tags"] = httpx.get("http://127.0.0.1:11434/api/tags", trust_env=False).json()
    json_write(target("manifest.json"), manifest)
    with target("server.log").open("x", encoding="utf-8") as server_log:
        process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "evaluate_reranked_generation:create_evaluation_app",
            "--factory", "--app-dir", str(PROJECT / "scripts"), "--host", "127.0.0.1",
            "--port", "8014", "--no-access-log",
        ], cwd=PROJECT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(base_url="http://127.0.0.1:8014", trust_env=False,
                              timeout=httpx.Timeout(330, connect=5)) as client:
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
                index = client.post("/documents/index", json={
                    "source_paths": sorted(PUBLIC_SOURCE_HASHES), "rebuild": True,
                })
                index.raise_for_status()
                if index.json() != {"indexed_documents": 5, "indexed_chunks": 52}:
                    raise ValueError("unexpected public index")
                started = perf_counter()
                client.get("/ready").raise_for_status()
                json_write(target("ready.json"), {"seconds": round(perf_counter() - started, 6)})
                print(f"ready; provider={args.provider} selected={len(selected)}; exact prompt gate active", flush=True)
                with target("attempts.jsonl").open("x", encoding="utf-8") as attempts, \
                        target("responses.jsonl").open("x", encoding="utf-8") as output:
                    def query(question):
                        attempts.write(json.dumps({"question": question,
                            "timestamp_utc": datetime.now(UTC).isoformat()}, ensure_ascii=False) + "\n")
                        attempts.flush()
                        started = perf_counter()
                        observation = {"api_query_attempted": True}
                        try:
                            response = client.post("/query", json={"query": question, "limit": 10})
                            observation.update({"http_status": response.status_code, "response": response.json()})
                            if response.status_code != 200:
                                observation["error_kind"] = "query_http_error"
                        except httpx.HTTPError:
                            observation["error_kind"] = "query_transport_error_no_retry"
                        observation["query_elapsed_seconds"] = round(perf_counter() - started, 6)
                        trace = read_lines(target("provider-trace.jsonl"))
                        matching = [row for row in trace if json.loads(row["request"]["user_prompt"])["question"] == question]
                        if len(matching) == 1:
                            payload = json.loads(matching[0]["request"]["user_prompt"])
                            observation.update({"actual_model_prompt_observed": True,
                                "context_capture_mode": "actual_model_request_before_provider",
                                "reconstructed_context": [asdict(approved[row["chunk_id"]]) for row in payload["context"]]})
                        else:
                            observation["error_kind"] = "model_trace_missing_or_ambiguous"
                        return observation

                    def persist(record):
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
                        output.flush()
                        print(args.provider, record["case_id"], record["status"], record.get("query_elapsed_seconds"), flush=True)
                        if record["status"] in {"error", "unavailable"} or record.get("query_elapsed_seconds", 0) > 390:
                            raise RuntimeError("stop after failure/execution gap; preserve all attempts, no automatic retry")

                    records = collect_generation(selected, query, on_result=persist)
                rubric = {row["case_id"]: row["required_points"]
                          for row in read_lines(DATA / "evaluation/answer-rubric-v1.jsonl")}
                with target("reviews-template.jsonl").open("x", encoding="utf-8") as output:
                    for row in make_review_template(records, rubric):
                        output.write(json.dumps(row, ensure_ascii=False) + "\n")
                json_write(target("summary-unreviewed.json"), summarize_generation(records))
                load_inputs()
                print(f"completed: {len(records)} actual queries; semantic review required", flush=True)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    if "--execute" in sys.argv:
        with idle_sleep_guard():
            main()
    else:
        main()
