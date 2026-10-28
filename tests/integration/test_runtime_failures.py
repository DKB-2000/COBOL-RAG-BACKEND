import logging

from fastapi.testclient import TestClient

from legacy_rag.api import dependencies
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult


class Searcher:
    def __init__(self):
        self.results = [SearchResult("public-id", "PUBLIC", "samples/a.cbl", "cobol", "A", "h", 0, 0.5)]

    def search(self, *, query, limit):
        return self.results


def test_readiness_requires_retrieval_and_nonempty_index_but_liveness_does_not():
    app = create_app()
    searcher = Searcher()
    app.dependency_overrides[dependencies.get_chunk_searcher] = lambda: searcher
    client = TestClient(app)
    assert client.get("/ready").json() == {"status": "ready"}
    searcher.results = []
    assert client.get("/ready").status_code == 503
    assert client.get("/ready").json() == {"detail": "index_empty"}
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_model_returns_safe_failure_and_health_stays_live(tmp_path, caplog):
    secret_path = tmp_path / "synthetic-private-model-directory"

    def missing_model():
        # Exercise the real local model loader behind the FastAPI dependency boundary.
        return dependencies.IdentifierAwareOnnxEmbedding(secret_path)

    app = create_app()
    app.dependency_overrides[dependencies.get_chunk_searcher] = missing_model
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="legacy_rag.requests"):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}
    assert secret_path.name not in response.text + caplog.text
    assert client.get("/health").status_code == 200


def test_unwritable_store_dependency_is_sanitized_and_can_recover(caplog):
    def bad_store():
        raise PermissionError("synthetic-private-store-path")

    app = create_app()
    app.dependency_overrides[dependencies.get_chunk_searcher] = bad_store
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="legacy_rag.requests"):
        response = client.post("/search", json={"query": "public"})
    assert response.status_code == 503
    assert "synthetic-private-store-path" not in response.text + caplog.text
    app.dependency_overrides[dependencies.get_chunk_searcher] = Searcher
    assert client.post("/search", json={"query": "public"}).status_code == 200


def test_index_error_never_echoes_source_or_exception(caplog):
    class InvalidIndexer:
        def index(self, **kwargs):
            raise ValueError("synthetic-private-source-path")

    app = create_app()
    app.dependency_overrides[dependencies.get_document_indexer] = InvalidIndexer
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="legacy_rag.requests"):
        response = client.post("/documents/index", json={"source_paths": ["synthetic-private-source-path"]})
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid_source"}
    assert "synthetic-private-source-path" not in response.text + caplog.text
