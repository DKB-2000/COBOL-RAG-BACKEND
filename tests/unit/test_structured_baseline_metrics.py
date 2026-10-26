import pytest

from legacy_rag.evaluation.structured_baseline import (
    build_contextual_embedding_text,
    rank_distinct_sources,
)
from legacy_rag.ingestion.models import SourceChunk
from legacy_rag.retrieval.chroma_store import SearchResult


def _result(source_path: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=f"{source_path}-{score}",
        text="chunk",
        source_path=source_path,
        language="cobol",
        symbol="SYMBOL",
        content_hash="hash",
        chunk_index=0,
        score=score,
    )


def test_rank_distinct_sources_uses_best_chunk_per_source() -> None:
    results = [
        _result("samples/a.cbl", 0.9),
        _result("samples/a.cbl", 0.8),
        _result("samples/b.cbl", 0.7),
        _result("samples/c.cbl", 0.6),
    ]

    ranked_sources = rank_distinct_sources(results, limit=2)

    assert ranked_sources == ["samples/a.cbl", "samples/b.cbl"]


def test_build_contextual_embedding_text_preserves_raw_chunk() -> None:
    chunk = SourceChunk(
        chunk_id="chunk-1",
        text="       APPLY-DEPOSIT.\n           CONTINUE.\n",
        source_path="samples/account-balance.cbl",
        language="cobol",
        symbol="APPLY-DEPOSIT",
        content_hash="hash",
        chunk_index=1,
    )

    embedding_text = build_contextual_embedding_text(chunk)

    assert embedding_text == (
        "Source path: samples/account-balance.cbl\n"
        "Symbol: APPLY-DEPOSIT\n\n"
        "       APPLY-DEPOSIT.\n"
        "           CONTINUE.\n"
    )
    assert chunk.text == "       APPLY-DEPOSIT.\n           CONTINUE.\n"


@pytest.mark.parametrize("source_path", ["C:/private/source.cbl", "../outside.cbl"])
def test_build_contextual_embedding_text_rejects_unsafe_path(source_path: str) -> None:
    chunk = SourceChunk(
        chunk_id="chunk-1",
        text="text",
        source_path=source_path,
        language="cobol",
        symbol="SYMBOL",
        content_hash="hash",
        chunk_index=0,
    )

    with pytest.raises(ValueError, match="relative data path"):
        build_contextual_embedding_text(chunk)
