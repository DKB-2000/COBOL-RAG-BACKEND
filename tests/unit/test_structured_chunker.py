from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.models import SourceDocument


def _document() -> SourceDocument:
    text = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SAMPLE.\n"
        "\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT SAMPLE-IN ASSIGN TO \"sample.dat\".\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-FLAG PIC X.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        "           PERFORM VALIDATE-INPUT.\n"
        "       VALIDATE-INPUT.\n"
        "           MOVE \"Y\" TO WS-FLAG.\n"
    )
    return SourceDocument(
        text=text,
        source_path="samples/sample.cbl",
        language="cobol",
        symbol="SAMPLE",
        content_hash="content-hash",
    )


def test_chunk_cobol_structure_preserves_boundaries_and_text() -> None:
    document = _document()

    chunks = chunk_cobol_structure(document)

    assert [chunk.symbol for chunk in chunks] == [
        "IDENTIFICATION DIVISION",
        "ENVIRONMENT DIVISION",
        "INPUT-OUTPUT SECTION",
        "DATA DIVISION",
        "WORKING-STORAGE SECTION",
        "PROCEDURE DIVISION",
        "MAIN-PROCESS",
        "VALIDATE-INPUT",
    ]
    assert "FILE-CONTROL" not in [chunk.symbol for chunk in chunks]
    assert "".join(chunk.text for chunk in chunks) == document.text
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.source_path == document.source_path for chunk in chunks)
    assert all(chunk.language == document.language for chunk in chunks)
    assert all(chunk.content_hash == document.content_hash for chunk in chunks)


def test_chunk_cobol_structure_reproduces_chunk_ids() -> None:
    document = _document()

    first_ids = [chunk.chunk_id for chunk in chunk_cobol_structure(document)]
    second_ids = [chunk.chunk_id for chunk in chunk_cobol_structure(document)]

    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))
