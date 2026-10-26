from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embeddings, Where

from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.runner import RetrievalReport, evaluate_retrieval
from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_files
from legacy_rag.ingestion.models import SourceChunk
from legacy_rag.retrieval.chroma_store import ChromaChunkStore, SearchResult
from legacy_rag.retrieval.embedding_input import build_contextual_embedding_text

__all__ = [
    "StructuredBaselineResult", "build_contextual_embedding_text", "rank_distinct_sources",
    "run_structured_baseline",
]


@dataclass(frozen=True, slots=True)
class StructuredBaselineResult:
    report: RetrievalReport
    chunk_count: int
    retrieved_chunks_by_case_id: dict[str, tuple[SearchResult, ...]]


def rank_distinct_sources(results: list[SearchResult], *, limit: int) -> list[str]:
    ranked_sources: list[str] = []
    seen_sources: set[str] = set()

    for result in results:
        if result.source_path in seen_sources:
            continue

        seen_sources.add(result.source_path)
        ranked_sources.append(result.source_path)

        if len(ranked_sources) == limit:
            break

    return ranked_sources


def run_structured_baseline(
    *,
    data_root: Path,
    dataset_path: Path,
    collection: Collection,
    embed_texts: Callable[[list[str]], Embeddings],
    k: int,
    metadata_filter: Where | None = None,
    embedding_text_builder: Callable[[SourceChunk], str] | None = None,
) -> StructuredBaselineResult:
    samples_root = data_root / "samples"
    source_paths = sorted(
        path for path in samples_root.iterdir() if path.is_file() and path.suffix.lower() == ".cbl"
    )
    documents = load_cobol_files(source_paths, data_root=data_root)
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_cobol_structure(document)
    ]

    embedding_texts = [
        embedding_text_builder(chunk) if embedding_text_builder is not None else chunk.text
        for chunk in chunks
    ]
    chunk_embeddings = embed_texts(embedding_texts)
    store = ChromaChunkStore(collection)
    store.rebuild(chunks, embeddings=chunk_embeddings)

    cases = load_evaluation_cases(dataset_path)
    retrieved_chunks_by_question: dict[str, tuple[SearchResult, ...]] = {}

    def retrieve_sources(question: str, limit: int) -> list[str]:
        query_embeddings = embed_texts([question])
        query_embedding = [float(value) for value in query_embeddings[0]]
        results = store.search(
            query_embedding=query_embedding,
            limit=len(chunks),
            where=metadata_filter,
        )
        retrieved_chunks_by_question[question] = tuple(results[:10])
        return rank_distinct_sources(results, limit=limit)

    report = evaluate_retrieval(cases, retrieve_sources, k=k)
    retrieved_chunks_by_case_id = {
        case.id: retrieved_chunks_by_question[case.question]
        for case in cases
        if case.answerable
    }
    return StructuredBaselineResult(
        report=report,
        chunk_count=len(chunks),
        retrieved_chunks_by_case_id=retrieved_chunks_by_case_id,
    )
