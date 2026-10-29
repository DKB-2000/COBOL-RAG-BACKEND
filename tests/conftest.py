import pytest


@pytest.fixture(autouse=True)
def historical_retrieval_for_offline_tests(monkeypatch):
    """Existing fixtures stay offline; reranking integration tests explicitly opt in."""
    monkeypatch.setenv("LEGACY_RAG_RERANKING", "disabled")
