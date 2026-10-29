"""Compare local Qwen3 with saved API v2 results; --execute runs 30 local queries."""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter, sleep

import httpx
from evaluate_generation import HttpProbe, json_write

from legacy_rag.api.dependencies import ApiSettings, OllamaSettings, get_generation_model
from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES, load_public_chunks
from legacy_rag.evaluation.answer_metrics import summarize_generation
from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.generation_runner import collect_generation, make_review_template
from legacy_rag.generation.models import GeneratedAnswer
from legacy_rag.generation.ollama_model import OllamaGenerationModel
from legacy_rag.generation.prompt import SYSTEM_PROMPT
from legacy_rag.main import create_app
from legacy_rag.retrieval.context import assemble_context

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
HERE = PROJECT / "artifacts"
BASELINE = DATA / "evaluation/results/generation-evaluation-v2.json"


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()]


def validate_reference(cases, records, baseline, project=PROJECT):
    if len(cases) != 30 or sum(case.answerable for case in cases) != 24:
        raise ValueError("expected the fixed 24+6 public cases")
    if len(records) != 30 or len({row["case_id"] for row in records}) != 30:
        raise ValueError("baseline must cover 30 unique cases")
    by_id = {row["case_id"]: row for row in records}
    if any(case.id not in by_id or by_id[case.id]["question"] != case.question for case in cases):
        raise ValueError("baseline questions differ")
    if any(sha256((project / path).read_bytes()).hexdigest() != digest
           for path, digest in baseline["input_hashes"].items()):
        raise ValueError("baseline input hashes changed")
    if baseline["system_prompt_sha256"] != sha256(SYSTEM_PROMPT.encode()).hexdigest():
        raise ValueError("baseline system prompt changed")
    return by_id


def verify_context(case, context, reference):
    expected = reference["reconstructed_context"]
    actual = [{key: getattr(chunk, key) for key in
               ("chunk_id", "text", "source_path", "symbol")} for chunk in context]
    frozen = [{key: row[key] for key in ("chunk_id", "text", "source_path", "symbol")}
              for row in expected]
    if actual != frozen:
        raise ValueError(f"baseline context differs for {case.id}; no generation permitted")


def pending_cases(cases, completed):
    by_id = {case.id: case for case in cases}
    if len({row["case_id"] for row in completed}) != len(completed):
        raise ValueError("duplicate completed cases")
    for row in completed:
        case = by_id.get(row["case_id"])
        if case is None or row["question"] != case.question or row["answerable"] != case.answerable:
            raise ValueError("completed case differs from reference")
    finished = {row["case_id"] for row in completed}
    return [case for case in cases if case.id not in finished]


@contextmanager
def idle_sleep_guard():
    if os.name != "nt":
        yield
        return
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
    kernel.SetThreadExecutionState.restype = ctypes.c_uint32
    if not kernel.SetThreadExecutionState(0x80000001):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        print("idle_sleep_guard_active", flush=True)
        yield
    finally:
        kernel.SetThreadExecutionState(0x80000000)
        print("idle_sleep_guard_released", flush=True)


def create_evaluation_app():
    """Separate actual API with an observed local model; no production server changes."""
    if ApiSettings().generation_provider != "ollama":
        raise ValueError("local evaluation requires ollama")
    trace_path = Path(os.environ["LEGACY_RAG_EVALUATION_TRACE"])
    settings = OllamaSettings()
    observed = {}

    def capture(response):
        response.read()
        observed["http_status"] = response.status_code
        try:
            observed["provider_response"] = response.json()
        except ValueError:
            observed["provider_decode_error"] = True

    client = httpx.Client(
        base_url="http://127.0.0.1:11434", trust_env=False, follow_redirects=False,
        timeout=httpx.Timeout(settings.ollama_timeout_seconds, connect=5),
        event_hooks={"response": [capture]},
    )
    adapter = OllamaGenerationModel(client=client,
                                    max_output_tokens=settings.ollama_max_output_tokens)

    class ObservedModel:
        def generate(self, request):
            observed.clear()
            observed["request"] = asdict(request)
            started = perf_counter()
            try:
                return adapter.generate(request)
            except Exception as exc:
                observed["adapter_error_kind"] = type(exc).__name__
                raise
            finally:
                observed["generation_elapsed_seconds"] = round(perf_counter() - started, 6)
                with trace_path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(observed, ensure_ascii=False) + "\n")

    app = create_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original_lifespan(app):
                yield
        finally:
            adapter.close()

    app.router.lifespan_context = lifespan
    model = ObservedModel()
    app.dependency_overrides[get_generation_model] = lambda: model
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prefix", default="ollama-generation-v1")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--resume-from", help="Preserve this prefix and collect only missing cases")
    selection.add_argument("--case-id", action="append",
                           help="Explicit environmental remeasurement; repeat for multiple cases")
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9-]+", args.prefix) is None:
        raise ValueError("prefix must be a filename")
    cases = load_evaluation_cases(DATA / "evaluation/questions-v1.jsonl")
    reference = validate_reference(cases, read_lines(HERE / "generation-v2-responses.jsonl"),
                                   json.loads(BASELINE.read_text(encoding="utf-8")))
    approved = load_public_chunks(DATA)
    if len(approved) != 52:
        raise ValueError("public corpus changed")
    selected = cases
    if args.resume_from:
        if re.fullmatch(r"[a-z0-9-]+", args.resume_from) is None or args.resume_from == args.prefix:
            raise ValueError("resume requires a different safe output prefix")
        previous = json.loads((HERE / f"{args.resume_from}-manifest.json").read_text(encoding="utf-8"))
        model_hash = sha256((PROJECT / "src/legacy_rag/generation/ollama_model.py").read_bytes()).hexdigest()
        if previous["model_code_sha256"] != model_hash:
            raise ValueError("adapter changed since interrupted run")
        selected = pending_cases(cases, read_lines(HERE / f"{args.resume_from}-responses.jsonl"))
    elif args.case_id:
        requested = set(args.case_id)
        selected = [case for case in cases if case.id in requested]
        if len(requested) != len(args.case_id) or len(selected) != len(requested):
            raise ValueError("unknown case ID")
    if not selected:
        raise ValueError("no pending cases")
    if not args.execute:
        print(f"preflight_inputs_ok: 30 reference cases, selected={len(selected)}; generation_calls=0")
        return

    with socket.socket() as port_check:
        port_check.bind(("127.0.0.1", 8012))

    def target(suffix):
        return HERE / f"{args.prefix}-{suffix}"

    # Reserve output once. Interrupted runs must not silently repeat generation.
    with target("reserved.json").open("x", encoding="utf-8") as output:
        json.dump({"started_at_utc": datetime.now(UTC).isoformat()}, output)
    target("provider-trace.jsonl").touch(exist_ok=False)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("LEGACY_RAG_") and key not in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}}
    env.update({
        "LEGACY_RAG_GENERATION_PROVIDER": "ollama", "LEGACY_RAG_RETRIEVAL_PROFILE": "identifier-aware",
        "LEGACY_RAG_RERANKING": "disabled", "LEGACY_RAG_DATA_ROOT": str(DATA),
        "LEGACY_RAG_CHROMA_PATH": str(target("chroma")),
        "LEGACY_RAG_OLLAMA_TIMEOUT_SECONDS": "300", "LEGACY_RAG_OLLAMA_MAX_OUTPUT_TOKENS": "1024",
        "LEGACY_RAG_EVALUATION_TRACE": str(target("provider-trace.jsonl")),
        "PYTHONUTF8": "1",
    })
    with target("server.log").open("x", encoding="utf-8") as server_log:
        process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "evaluate_ollama:create_evaluation_app", "--factory",
            "--app-dir", str(PROJECT / "scripts"), "--host", "127.0.0.1", "--port", "8012",
            "--no-access-log",
        ], cwd=PROJECT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(base_url="http://127.0.0.1:8012", trust_env=False,
                              timeout=httpx.Timeout(330, connect=5)) as client:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError("isolated API exited; see server log")
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
                probe = HttpProbe(client, approved)
                for case in cases:
                    verify_context(case, assemble_context(probe.search(case.question)),
                                   reference[case.id])
                manifest = {
                    "created_at_utc": datetime.now(UTC).isoformat(), "model": "qwen3:4b",
                    "provider": "ollama", "model_details": httpx.get(
                        "http://127.0.0.1:11434/api/tags", trust_env=False).json(),
                    "cases": len(selected), "max_queries": len(selected), "retries": 0,
                    "reference_cases": 30, "selected_case_ids": [case.id for case in selected],
                    "resume_from": args.resume_from, "environmental_remeasurement": args.case_id,
                    "baseline": str(BASELINE.relative_to(PROJECT)), "context_matches": 30,
                    "input_hashes": json.loads(BASELINE.read_text(encoding="utf-8"))["input_hashes"],
                    "system_prompt_sha256": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                    "schema_sha256": sha256(json.dumps(GeneratedAnswer.model_json_schema(),
                                                       sort_keys=True).encode()).hexdigest(),
                    "measurement": "sequential actual HTTP /query, including retrieval/generation",
                    "num_predict": 1024, "num_ctx": 8192, "think": False, "keep_alive": 0,
                    "baseline_output_limit": 1000, "baseline_reasoning": "none",
                    "model_code_sha256": sha256((PROJECT / "src/legacy_rag/generation/ollama_model.py")
                                                .read_bytes()).hexdigest(),
                }
                json_write(target("manifest.json"), manifest)
                print(f"preflight_contexts_match=30/30; starting {len(selected)} local queries", flush=True)
                with target("attempts.jsonl").open("x", encoding="utf-8") as journal, \
                        target("responses.jsonl").open("x", encoding="utf-8") as output:
                    probe = HttpProbe(client, approved, max_queries=len(selected), journal=journal)

                    def persist(record):
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
                        output.flush()
                        print(record["case_id"], record["status"],
                              record.get("query_elapsed_seconds"), flush=True)
                        if record.get("query_elapsed_seconds", 0) > 390:
                            raise RuntimeError("execution gap exceeds timeout; preserve result and resume while awake")

                    records = collect_generation(selected, probe, on_result=persist)
                rubric = {row["case_id"]: row["required_points"]
                          for row in read_lines(DATA / "evaluation/answer-rubric-v1.jsonl")}
                with target("reviews-template.jsonl").open("x", encoding="utf-8") as output:
                    for row in make_review_template(records, rubric):
                        output.write(json.dumps(row, ensure_ascii=False) + "\n")
                json_write(target("summary-unreviewed.json"), summarize_generation(records))
                validate_reference(cases, list(reference.values()),
                                   json.loads(BASELINE.read_text(encoding="utf-8")))
                print(f"completed: {len(records)} local cases; semantic review still required", flush=True)
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
