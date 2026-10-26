from collections.abc import Iterable

from legacy_rag.retrieval.chroma_store import SearchResult


def assemble_context(
    results: Iterable[SearchResult], *, max_chars: int = 4000, max_chunks: int = 10
) -> tuple[SearchResult, ...]:
    """Keep whole, nonblank chunks in retrieval order within a raw-text budget."""
    selected = []
    seen = set()
    length = 0
    for result in results:
        if len(selected) >= max_chunks:
            break
        if result.chunk_id in seen:
            continue
        seen.add(result.chunk_id)
        if not result.text.strip() or length + len(result.text) > max_chars:
            continue
        selected.append(result)
        length += len(result.text)
    return tuple(selected)
