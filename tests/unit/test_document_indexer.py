from dataclasses import dataclass, field
from pathlib import Path

import pytest

from legacy_rag.api.services import FileDocumentIndexer
from legacy_rag.ingestion.models import SourceChunk


@dataclass
class FakeChunkStore:
    rebuilt_chunks: list[SourceChunk] | None = None
    replaced_sources: list[tuple[str, list[SourceChunk]]] = field(default_factory=list)

    def rebuild(self, chunks: list[SourceChunk]) -> None:
        self.rebuilt_chunks = chunks

    def replace_source(self, *, source_path: str, chunks: list[SourceChunk]) -> None:
        self.replaced_sources.append((source_path, chunks))


def _write_cobol(path: Path, program_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"       PROGRAM-ID. {program_id}.\n", encoding="utf-8")


def test_file_document_indexer_rebuilds_relative_sources(tmp_path: Path) -> None:
    _write_cobol(tmp_path / "samples" / "one.cbl", "ONE")
    _write_cobol(tmp_path / "samples" / "two.cbl", "TWO")
    store = FakeChunkStore()
    indexer = FileDocumentIndexer(data_root=tmp_path, store=store)

    result = indexer.index(
        source_paths=["samples/one.cbl", "samples/two.cbl"],
        rebuild=True,
    )

    assert result.indexed_documents == 2
    assert result.indexed_chunks == 2
    assert store.rebuilt_chunks is not None
    assert [chunk.source_path for chunk in store.rebuilt_chunks] == [
        "samples/one.cbl",
        "samples/two.cbl",
    ]
    assert store.replaced_sources == []


def test_file_document_indexer_rejects_path_outside_data_root(tmp_path: Path) -> None:
    outside_path = tmp_path.parent / "outside.cbl"
    _write_cobol(outside_path, "OUTSIDE")
    store = FakeChunkStore()
    indexer = FileDocumentIndexer(data_root=tmp_path, store=store)

    with pytest.raises(ValueError, match="outside data root"):
        indexer.index(source_paths=[str(outside_path)], rebuild=True)

    assert store.rebuilt_chunks is None
    assert store.replaced_sources == []
