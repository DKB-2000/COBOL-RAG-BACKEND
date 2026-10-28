from pathlib import Path

from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_file
from legacy_rag.ingestion.models import SourceChunk
from legacy_rag.retrieval.chroma_store import SearchResult

# API approval boundary: the original five self-authored synthetic samples.
# Hashes use UTF-8 text after newline normalization, matching the loader contract.
PUBLIC_SOURCE_HASHES = {
    "samples/account-balance.cbl": "c79d66239aa3d9100963d2dd9a8311f1b7240566c9856eb2b85d199d9cfd0a94",
    "samples/customer-import.cbl": "ab96e679a7235db1758437fdec27f8bae6a86fc5f7a04d90838c07423fdd4468",
    "samples/daily-report.cbl": "f251a2315401119ad74ba4f3d898977cc883a18056baf358ab61997b9e4daaab",
    "samples/date-utility.cbl": "d4f1f8ae2e9c2eaf1969d6374020868e54fef9b194a6976da0f72ee8efa8e105",
    "samples/transaction-post.cbl": "309f16976d118e8377a5800d4892404b3d1aba4b802df944ad099cfa0ccc74c7",
}


def load_public_chunks(data_root: Path) -> dict[str, SourceChunk]:
    approved = {}
    for relative_path, digest in PUBLIC_SOURCE_HASHES.items():
        try:
            document = load_cobol_file(data_root / relative_path, data_root=data_root)
        except (OSError, ValueError):
            continue
        if document.content_hash == digest:
            approved.update((c.chunk_id, c) for c in chunk_cobol_structure(document))
    return approved


def is_public_chunk(result: SearchResult, approved: dict[str, SourceChunk]) -> bool:
    chunk = approved.get(result.chunk_id)
    return chunk is not None and all(
        getattr(result, name) == getattr(chunk, name)
        for name in ("text", "source_path", "language", "symbol", "content_hash", "chunk_index")
    )
