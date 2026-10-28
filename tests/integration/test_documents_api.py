from dataclasses import dataclass

from fastapi.testclient import TestClient

from legacy_rag.api.dependencies import get_document_indexer
from legacy_rag.api.services import IndexingResult
from legacy_rag.main import create_app


@dataclass
class FakeDocumentIndexer:
    received_paths: list[str] | None = None
    received_rebuild: bool | None = None

    def index(self, *, source_paths: list[str], rebuild: bool) -> IndexingResult:
        self.received_paths = source_paths
        self.received_rebuild = rebuild
        return IndexingResult(indexed_documents=2, indexed_chunks=2)


class RejectingDocumentIndexer:
    def index(self, *, source_paths: list[str], rebuild: bool) -> IndexingResult:
        raise ValueError("source path is outside data root")


def test_index_documents_uses_injected_indexer() -> None:
    indexer = FakeDocumentIndexer()
    app = create_app()
    app.dependency_overrides[get_document_indexer] = lambda: indexer

    response = TestClient(app).post(
        "/documents/index",
        json={
            "source_paths": ["samples/one.cbl", "samples/two.cbl"],
            "rebuild": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"indexed_documents": 2, "indexed_chunks": 2}
    assert indexer.received_paths == ["samples/one.cbl", "samples/two.cbl"]
    assert indexer.received_rebuild is True


def test_index_documents_returns_bad_request_for_invalid_source() -> None:
    app = create_app()
    app.dependency_overrides[get_document_indexer] = RejectingDocumentIndexer

    response = TestClient(app).post(
        "/documents/index",
        json={"source_paths": ["../outside.cbl"], "rebuild": False},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid_source"}


def test_index_documents_rejects_empty_source_paths() -> None:
    app = create_app()
    app.dependency_overrides[get_document_indexer] = FakeDocumentIndexer

    response = TestClient(app).post(
        "/documents/index",
        json={"source_paths": [], "rebuild": False},
    )

    assert response.status_code == 422
