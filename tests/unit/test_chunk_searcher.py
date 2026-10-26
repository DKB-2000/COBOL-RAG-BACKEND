from dataclasses import dataclass

from legacy_rag.api.services import VectorChunkSearcher
from legacy_rag.retrieval.chroma_store import SearchResult


@dataclass
class FakeSearchStore:
    received_embedding: list[float] | None = None
    received_limit: int | None = None

    def search(self, *, query_embedding: list[float], limit: int) -> list[SearchResult]:
        self.received_embedding = query_embedding
        self.received_limit = limit
        return []


def test_vector_chunk_searcher_embeds_query_before_store_search() -> None:
    store = FakeSearchStore()
    received_texts: list[str] = []

    def embed_texts(texts: list[str]) -> list[list[float]]:
        received_texts.extend(texts)
        return [[0.1, 0.2, 0.3]]

    searcher = VectorChunkSearcher(store=store, embed_texts=embed_texts)

    results = searcher.search(query="잔액 계산", limit=3)

    assert results == []
    assert received_texts == ["잔액 계산"]
    assert store.received_embedding == [0.1, 0.2, 0.3]
    assert store.received_limit == 3
