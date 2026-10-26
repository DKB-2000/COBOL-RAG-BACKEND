from dataclasses import dataclass

from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embeddings, Where

from legacy_rag.ingestion.models import SourceChunk


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_id: str
    text: str
    source_path: str
    language: str
    symbol: str
    content_hash: str
    chunk_index: int
    score: float


class ChromaChunkStore:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def rebuild(
        self,
        chunks: list[SourceChunk],
        *,
        embeddings: Embeddings | None = None,
    ) -> None:
        existing = self._collection.get(
            include=[],
        )
        existing_ids = existing["ids"]

        if existing_ids:
            self._collection.delete(
                ids=existing_ids,
            )

        self.upsert(
            chunks,
            embeddings=embeddings,
        )

    def upsert(
        self,
        chunks: list[SourceChunk],
        *,
        embeddings: Embeddings | None = None,
    ) -> None:
        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "source_path": chunk.source_path,
                "language": chunk.language,
                "symbol": chunk.symbol,
                "content_hash": chunk.content_hash,
                "chunk_index": chunk.chunk_index,
            }
            for chunk in chunks
        ]

        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def replace_source(
        self,
        *,
        source_path: str,
        chunks: list[SourceChunk],
        embeddings: Embeddings | None = None,
    ) -> None:
        self._collection.delete(
            where={"source_path": source_path},
        )
        self.upsert(
            chunks,
            embeddings=embeddings,
        )

    def search(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        where: Where | None = None,
    ) -> list[SearchResult]:
        raw_result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
            where=where,
        )

        documents = raw_result["documents"]
        metadatas = raw_result["metadatas"]
        distances = raw_result["distances"]

        if documents is None or metadatas is None or distances is None:
            raise RuntimeError("Chroma search result is incomplete")

        results: list[SearchResult] = []

        for index, chunk_id in enumerate(raw_result["ids"][0]):
            document = documents[0][index]
            metadata = metadatas[0][index]

            if document is None or metadata is None:
                raise RuntimeError("Chroma search result is incomplete")

            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    text=document,
                    source_path=str(metadata["source_path"]),
                    language=str(metadata["language"]),
                    symbol=str(metadata["symbol"]),
                    content_hash=str(metadata["content_hash"]),
                    chunk_index=int(metadata["chunk_index"]),
                    score=1.0 - float(distances[0][index]),
                )
            )

        return results
