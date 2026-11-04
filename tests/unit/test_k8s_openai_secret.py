"""Credential transport must keep secrets out of process arguments and diagnostics."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "k8s_secret", Path(__file__).resolve().parents[2] / "scripts/prepare_k8s_openai_secret.py",
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_key_only_goes_through_stdin(monkeypatch, capsys):
    secret = "synthetic-test-secret"
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(helper.subprocess, "run", run)
    helper.create_secret(secret)
    assert all(secret not in arg for argv, _ in calls for arg in argv)
    assert json.loads(calls[1][1]["input"])["stringData"]["OPENAI_API_KEY"] == secret
    assert capsys.readouterr().out == ""


def test_server_error_does_not_echo_submitted_secret(monkeypatch):
    secret = "synthetic-secret-in-unsafe-server-error"
    replies = iter([
        SimpleNamespace(returncode=0, stdout=""),
        SimpleNamespace(returncode=1, stdout=secret, stderr=secret),
    ])
    monkeypatch.setattr(helper.subprocess, "run", lambda *a, **kw: next(replies))
    with pytest.raises(RuntimeError) as error:
        helper.create_secret(secret)
    assert secret not in str(error.value)


def test_existing_secret_is_never_overwritten(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="secret/rag-openai-credentials")

    monkeypatch.setattr(helper.subprocess, "run", run)
    with pytest.raises(FileExistsError):
        helper.create_secret("synthetic-test-secret")
    assert len(calls) == 1
