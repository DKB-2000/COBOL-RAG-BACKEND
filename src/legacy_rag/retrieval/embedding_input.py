from pathlib import Path

from legacy_rag.ingestion.models import SourceChunk


def build_contextual_embedding_text(chunk: SourceChunk) -> str:
    source_path = Path(chunk.source_path)
    if source_path.is_absolute() or ".." in source_path.parts:
        raise ValueError("source_path must be a relative data path")
    return (
        f"Source path: {chunk.source_path}\n"
        f"Symbol: {chunk.symbol}\n\n"
        f"{chunk.text}"
    )
