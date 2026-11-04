"""Create the dedicated lab Secret from ENV without putting the key in files or argv."""
import argparse
import json
import os
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SECRET_NAME = "rag-openai-credentials"
KUBECTL = [
    "kubectl", "--kubeconfig", str(PROJECT / "artifacts/k8s-lab-v1.kubeconfig"),
    "--context", "kind-legacy-rag-lab", "-n", "legacy-rag-lab",
]


def read_key():
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value and os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as environment:
                value = winreg.QueryValueEx(environment, "OPENAI_API_KEY")[0].strip()
        except FileNotFoundError:
            pass
    return value


def create_secret(key):
    existing = subprocess.run(
        KUBECTL + ["get", "secret", SECRET_NAME, "--ignore-not-found", "-o", "name"],
        text=True, capture_output=True, check=False, timeout=30,
    )
    if existing.returncode:
        raise RuntimeError("could not check the dedicated lab Secret; details omitted")
    if existing.stdout.strip():
        raise FileExistsError("lab Secret already exists; do not overwrite credentials")
    payload = {
        "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
        "metadata": {"name": SECRET_NAME, "namespace": "legacy-rag-lab"},
        "stringData": {"OPENAI_API_KEY": key},
    }
    result = subprocess.run(
        KUBECTL + ["create", "-f", "-"], input=json.dumps(payload), text=True,
        capture_output=True, check=False, timeout=30,
    )
    # Server error output may include submitted data; never relay it.
    if result.returncode:
        raise RuntimeError("could not create the lab Secret; server details omitted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    key = read_key()
    if not key:
        parser.error("OPENAI_API_KEY is missing from process/user ENV; do not paste it into chat")
    if args.execute:
        create_secret(key)
    print("key_available=True secret_created=" + str(args.execute) + " model_calls=0")


if __name__ == "__main__":
    main()
