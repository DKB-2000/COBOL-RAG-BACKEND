import json
from pathlib import Path

import chromadb
import pytest

from legacy_rag.evaluation.structured_baseline import (
    build_contextual_embedding_text,
    run_structured_baseline,
)


def _write_source(path: Path, *, program_id: str, field_name: str) -> None:
    path.write_text(
        (
            "       IDENTIFICATION DIVISION.\n"
            f"       PROGRAM-ID. {program_id}.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            f"       01  {field_name} PIC X.\n"
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("contextual", [False, True])
def test_run_structured_baseline_ranks_distinct_sources(
    tmp_path: Path, contextual: bool,
) -> None:
    data_root = tmp_path / "data"
    samples_root = data_root / "samples"
    samples_root.mkdir(parents=True)
    _write_source(samples_root / "target.cbl", program_id="TARGET", field_name="TARGET-FIELD")
    _write_source(samples_root / "other.cbl", program_id="OTHER", field_name="OTHER-FIELD")

    dataset_path = data_root / "questions.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "id": "q001",
                "question": "target question",
                "expected_sources": ["samples/target.cbl"],
                "expected_symbols": ["TARGET-FIELD"],
                "answerable": True,
                "tags": ["cobol"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    collection = chromadb.PersistentClient(path=str(tmp_path / "chroma")).create_collection(
        name="structured-test",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )

    embedding_inputs: list[list[str]] = []

    def embed_texts(texts: list[str]) -> list[list[float]]:
        embedding_inputs.append(texts)
        return [
            [1.0, 0.0] if text == "target question" or "TARGET-FIELD" in text else [0.0, 1.0]
            for text in texts
        ]

    result = run_structured_baseline(
        data_root=data_root,
        dataset_path=dataset_path,
        collection=collection,
        embed_texts=embed_texts,
        embedding_text_builder=build_contextual_embedding_text if contextual else None,
        k=2,
    )

    assert result.chunk_count == 6
    assert collection.count() == 6
    stored = collection.get(include=["documents", "metadatas"])
    stored_documents = stored["documents"]
    assert stored_documents is not None
    metadatas = stored["metadatas"]
    assert metadatas is not None
    for source in samples_root.glob("*.cbl"):
        source_chunks = sorted(
            (metadata["chunk_index"], document)
            for document, metadata in zip(stored_documents, metadatas, strict=True)
            if metadata["source_path"] == source.relative_to(data_root).as_posix()
        )
        assert "".join(text for _, text in source_chunks) == source.read_text(encoding="utf-8")
    expected_embedding_inputs = sorted(
        f"Source path: {metadata['source_path']}\nSymbol: {metadata['symbol']}\n\n{document}"
        if contextual else document
        for document, metadata in zip(stored_documents, metadatas, strict=True)
    )
    assert sorted(embedding_inputs[0]) == expected_embedding_inputs
    assert embedding_inputs[1:] == [["target question"]]
    assert result.report.hit_at_k == 1.0
    assert result.report.mrr == 1.0
    assert result.report.case_results[0].retrieved_sources[0] == "samples/target.cbl"
