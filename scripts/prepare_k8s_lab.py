"""Render a dedicated kind config using existing local models; no cluster mutations."""
import argparse
import json
from pathlib import Path

from legacy_rag.retrieval.embedding import MODEL_ID, MODEL_REVISION
from legacy_rag.retrieval.reranking import RERANKER_ID, RERANKER_REVISION

PROJECT = Path(__file__).resolve().parents[1]
CLUSTER = "legacy-rag-lab"
NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:"
    "099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=PROJECT / "artifacts/k8s-lab-v1-kind.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve the original config")
    models = PROJECT / "data/models"
    mounts = [
        (PROJECT / "data/samples", "samples"),
        (models / ("models--" + MODEL_ID.replace("/", "--"))
         / "snapshots" / MODEL_REVISION, "models"),
        (models / ("models--" + RERANKER_ID.replace("/", "--"))
         / "snapshots" / RERANKER_REVISION, "reranker"),
    ]
    for source, _ in mounts:
        if not source.is_dir():
            parser.error("required local sample/model directory is missing")
    state = PROJECT / "artifacts/k8s-lab-v1-chroma"
    state.mkdir(parents=True, exist_ok=True)
    extra_mounts = [
        {"hostPath": source.resolve().as_posix(),
         "containerPath": "/var/local/legacy-rag/" + name, "readOnly": True}
        for source, name in mounts
    ]
    extra_mounts.append({"hostPath": state.resolve().as_posix(),
                         "containerPath": "/var/local/legacy-rag/chroma"})
    config = {
        "kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "name": CLUSTER,
        "networking": {"apiServerAddress": "127.0.0.1"},
        "nodes": [{"role": "control-plane", "image": NODE_IMAGE,
                   "extraMounts": extra_mounts}],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("kind config:", args.output.resolve())
    print("dedicated Chroma directory:", state)
    print("Existing models are reused read-only; generation is configured separately.")


if __name__ == "__main__":
    main()
