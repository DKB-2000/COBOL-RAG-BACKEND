from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from legacy_rag.api.dependencies import get_chunk_searcher
from legacy_rag.main import create_app
from legacy_rag.retrieval.chroma_store import SearchResult


@dataclass
class FakeChunkSearcher:
    received_query: str | None = None
    received_limit: int | None = None

    def search(self, *, query: str, limit: int) -> list[SearchResult]:
        self.received_query = query
        self.received_limit = limit
        return [
            SearchResult(
                chunk_id="chunk-1",
                text="       PROGRAM-ID. HELLO.\n",
                source_path="samples/hello.cbl",
                language="cobol",
                symbol="HELLO",
                content_hash="content-hash",
                chunk_index=0,
                score=0.75,
            )
        ]


def test_search_returns_ranked_chunks_from_injected_searcher() -> None:
    searcher = FakeChunkSearcher()
    app = create_app()
    app.dependency_overrides[get_chunk_searcher] = lambda: searcher

    response = TestClient(app).post(
        "/search",
        json={"query": "인사 프로그램은?", "limit": 3},
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "chunk_id": "chunk-1",
                "text": "       PROGRAM-ID. HELLO.\n",
                "source_path": "samples/hello.cbl",
                "language": "cobol",
                "symbol": "HELLO",
                "chunk_index": 0,
                "score": 0.75,
            }
        ]
    }
    assert searcher.received_query == "인사 프로그램은?"
    assert searcher.received_limit == 3


@pytest.mark.parametrize(
    ("payload"),
    [
        {"query": "", "limit": 3},
        {"query": "잔액 계산", "limit": 0},
        {"query": "잔액 계산", "limit": 51},
    ],
)
def test_search_rejects_invalid_request(payload: dict[str, object]) -> None:
    app = create_app()
    app.dependency_overrides[get_chunk_searcher] = FakeChunkSearcher

    response = TestClient(app).post("/search", json=payload)

    assert response.status_code == 422
