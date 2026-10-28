from hashlib import sha256
from pathlib import Path

import pytest

from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_file
from legacy_rag.ingestion.models import SourceDocument


def test_numbered_source_preserves_structure_and_original_text() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures"
    document = load_cobol_file(root / "numbered-structure.cbl", data_root=root)

    chunks = chunk_cobol_structure(document)

    assert [chunk.symbol for chunk in chunks] == [
        "IDENTIFICATION DIVISION", "ENVIRONMENT DIVISION", "INPUT-OUTPUT SECTION",
        "DATA DIVISION", "WORKING-STORAGE SECTION", "PROCEDURE DIVISION",
        "MAIN-PROCESS", "READ-ITEM",
    ]
    assert "".join(chunk.text for chunk in chunks) == document.text
    assert [chunk.chunk_index for chunk in chunks] == list(range(8))
    assert all(chunk.source_path == document.source_path for chunk in chunks)
    assert all(chunk.content_hash == document.content_hash for chunk in chunks)
    assert all(chunk.language == "cobol" for chunk in chunks)
    assert chunks[-1].text.startswith("001800 READ-ITEM.")
    assert "001100*COMMENT-PARAGRAPH." in chunks[5].text
    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in chunk_cobol_structure(document)]
    assert len({c.chunk_id for c in chunks}) == 8


@pytest.mark.parametrize("sequence", ["000100", "12 345", "      "])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_boundary_ignores_sequence_and_identification_columns(sequence, newline) -> None:
    # The identification suffix starts at column73 and is preserved in the source slice.
    text = newline.join(
        (sequence + " " + code).ljust(72) + "CASE0001"
        for code in ["PROCEDURE DIVISION.", "MAIN-PROCESS.", "    GOBACK."]
    ) + newline
    document = SourceDocument(text, "numbered.cbl", "cobol", "SAMPLE", sha256(text.encode()).hexdigest())

    chunks = chunk_cobol_structure(document)

    assert [chunk.symbol for chunk in chunks] == ["PROCEDURE DIVISION", "MAIN-PROCESS"]
    assert "".join(c.text for c in chunks) == text
    assert "CASE0001" in chunks[0].text
