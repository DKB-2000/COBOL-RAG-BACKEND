from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from chromadb.api.types import Embeddings

from legacy_rag.ingestion.chunker import chunk_cobol_structure, chunk_document
from legacy_rag.ingestion.loader import load_cobol_files
from legacy_rag.ingestion.models import SourceChunk
from legacy_rag.retrieval.chroma_store import SearchResult
from legacy_rag.retrieval.embedding_input import build_contextual_embedding_text


@dataclass(frozen=True, slots=True)
class IndexingResult:
    indexed_documents: int
    indexed_chunks: int


class DocumentIndexer(Protocol):
    def index(self, *, source_paths: list[str], rebuild: bool) -> IndexingResult: ...


class ChunkStore(Protocol):
    def rebuild(
        self, chunks: list[SourceChunk], *, embeddings: Embeddings | None = None
    ) -> None: ...

    def replace_source(
        self, *, source_path: str, chunks: list[SourceChunk], embeddings: Embeddings | None = None
    ) -> None: ...


class ChunkSearchStore(Protocol):
    def search(self, *, query_embedding: list[float], limit: int) -> list[SearchResult]: ...


class ChunkSearcher(Protocol):
    def search(self, *, query: str, limit: int) -> list[SearchResult]: ...


class FileDocumentIndexer:
    def __init__(self, *, data_root: Path, store: ChunkStore) -> None:
        self._data_root = data_root
        self._store = store

    def index(self, *, source_paths: list[str], rebuild: bool) -> IndexingResult:
        paths = [self._data_root / source_path for source_path in source_paths]
        documents = load_cobol_files(paths, data_root=self._data_root)
        chunks = [chunk for document in documents for chunk in chunk_document(document)]

        if rebuild:
            self._store.rebuild(chunks)
        else:
            for document in documents:
                document_chunks = chunk_document(document)
                self._store.replace_source(
                    source_path=document.source_path,
                    chunks=document_chunks,
                )

        return IndexingResult(
            indexed_documents=len(documents),
            indexed_chunks=len(chunks),
        )


class StructuredDocumentIndexer:
    def __init__(
        self, *, data_root: Path, store: ChunkStore,
        embed_texts: Callable[[list[str]], Embeddings],
        allowed_source_hashes: dict[str, str] | None = None,
    ) -> None:
        self._data_root = data_root
        self._store = store
        self._embed_texts = embed_texts
        self._allowed_source_hashes = allowed_source_hashes

    def index(self, *, source_paths: list[str], rebuild: bool) -> IndexingResult:
        documents = load_cobol_files(
            [self._data_root / path for path in source_paths], data_root=self._data_root
        )
        if self._allowed_source_hashes is not None and any(
            self._allowed_source_hashes.get(doc.source_path) != doc.content_hash
            for doc in documents
        ):
            raise ValueError("source is not approved for external generation")
        groups = [chunk_cobol_structure(document) for document in documents]
        chunks = [chunk for group in groups for chunk in group]
        # Compute all embeddings before any destructive replacement.
        embeddings = self._embed_texts([build_contextual_embedding_text(chunk) for chunk in chunks])
        if rebuild:
            self._store.rebuild(chunks, embeddings=embeddings)
        else:
            offset = 0
            for document, group in zip(documents, groups, strict=True):
                self._store.replace_source(
                    source_path=document.source_path, chunks=group,
                    embeddings=embeddings[offset : offset + len(group)],
                )
                offset += len(group)
        return IndexingResult(indexed_documents=len(documents), indexed_chunks=len(chunks))


class VectorChunkSearcher:
    def __init__(
        self,
        *,
        store: ChunkSearchStore,
        embed_texts: Callable[[list[str]], Embeddings],
    ) -> None:
        self._store = store
        self._embed_texts = embed_texts

    def search(self, *, query: str, limit: int) -> list[SearchResult]:
        embeddings = self._embed_texts([query])
        query_embedding = [float(value) for value in embeddings[0]]
        return self._store.search(query_embedding=query_embedding, limit=limit)
