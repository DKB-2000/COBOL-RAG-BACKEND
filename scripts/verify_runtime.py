"""Check a loopback API's retrieval and persistence without calling /query or a provider."""
import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES

QUESTION = "잔액을 계산하는 프로그램은 무엇인가?"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--index", action="store_true", help="Index only the five public sources")
    parser.add_argument("--compare", type=Path, help="Compare search results with a previous report")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.output.exists():
        parser.error("output already exists; choose a new filename")
    previous = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    base = f"http://127.0.0.1:{args.port}"
    opener = build_opener(ProxyHandler({}))

    def call(route, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(base + route, data=body, headers={"Content-Type": "application/json"})
        started = perf_counter()
        try:
            with opener.open(request, timeout=5 if route == "/health" else 300) as response:
                result = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"{route} failed with HTTP {error.code}; response body omitted") from None
        except (URLError, TimeoutError):
            raise RuntimeError(f"{route} could not reach the loopback API within its timeout") from None
        return result, perf_counter() - started

    health, health_seconds = call("/health")
    if health != {"status": "ok"}:
        raise RuntimeError("Liveness check failed")
    index = index_seconds = None
    if args.index:
        index, index_seconds = call("/documents/index", {
            "source_paths": list(PUBLIC_SOURCE_HASHES), "rebuild": False,
        })
        if index != {"indexed_documents": 5, "indexed_chunks": 52}:
            raise RuntimeError("Unexpected public index result")
    ready, ready_seconds = call("/ready")
    if ready != {"status": "ready"}:
        raise RuntimeError("Retrieval readiness check failed")
    # The model is already initialized by indexing/readiness; keep this warmup separate.
    warmup, warmup_seconds = call("/search", {"query": QUESTION, "limit": 10})
    if not warmup.get("results"):
        raise RuntimeError("Search returned no indexed chunks")

    def fingerprint(response):
        fields = ("chunk_id", "text", "source_path", "language", "symbol", "chunk_index")
        stable = [{key: row[key] for key in fields} for row in response["results"]]
        return sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    expected = fingerprint(warmup)
    samples = []
    for _ in range(10):
        response, elapsed = call("/search", {"query": QUESTION, "limit": 10})
        if fingerprint(response) != expected:
            raise RuntimeError("Search results changed during the sequential measurement")
        samples.append(elapsed)
    persistent = previous["search_fingerprint"] == expected if previous else None
    report = {
        "created_at_utc": datetime.now(UTC).isoformat(), "base_url": base,
        "generation_calls": 0, "health_seconds": health_seconds,
        "index_result": index, "index_seconds_including_initialization": index_seconds,
        "ready_seconds": ready_seconds, "warmup_search_seconds": warmup_seconds,
        "search_fingerprint": expected, "retrieved_chunk_ids": [r["chunk_id"] for r in warmup["results"]],
        "warm_search_http_seconds": samples, "n": len(samples), "concurrency": 1,
        "percentile_method": "nearest_rank",
        "p50_seconds": sorted(samples)[ceil(len(samples) * 0.50) - 1],
        "p95_seconds": sorted(samples)[ceil(len(samples) * 0.95) - 1],
        "comparison_matches": persistent,
        "measurement_scope": "warm sequential /search HTTP; initialization/readiness/warmup reported separately",
        "limitations": "Small sample; no concurrency SLA or generation measurement; indexing is non-atomic",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if persistent is False:
        raise RuntimeError("Persistence comparison failed; report saved")
    print(f"retrieval_ok: n=10 paid_calls=0 persistence_matches={persistent}")
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
