from legacy_rag.ingestion.chunker import chunk_document
from legacy_rag.ingestion.models import SourceDocument


def test_chunk_document_creates_one_file_level_chunk() -> None:
    document = SourceDocument(
        text="       PROGRAM-ID. HELLO.\n",
        source_path="samples/hello.cbl",
        language="cobol",
        symbol="HELLO",
        content_hash="test-content-hash",
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1

    chunk = chunks[0]
    assert chunk.text == document.text
    assert chunk.source_path == document.source_path
    assert chunk.language == document.language
    assert chunk.symbol == document.symbol
    assert chunk.content_hash == document.content_hash
    assert chunk.chunk_index == 0
    assert chunk.chunk_id


def test_chunk_document_reproduces_chunk_id_for_same_input() -> None:
    document = SourceDocument(
        text="       PROGRAM-ID. HELLO.\n",
        source_path="samples/hello.cbl",
        language="cobol",
        symbol="HELLO",
        content_hash="test-content-hash",
    )

    first_chunk = chunk_document(document)[0]
    second_chunk = chunk_document(document)[0]

    assert first_chunk.chunk_id == second_chunk.chunk_id
