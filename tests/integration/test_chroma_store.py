from pathlib import Path

import chromadb
import pytest

from legacy_rag.ingestion.models import SourceChunk
from legacy_rag.retrieval.chroma_store import ChromaChunkStore


def test_chroma_persistent_client_round_trips_chunk(
    tmp_path: Path,
) -> None:
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"),
    )
    collection = client.create_collection(
        name="test-chunks",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )

    metadata = {
        "source_path": "samples/hello.cbl",
        "language": "cobol",
        "symbol": "HELLO",
        "content_hash": "test-content-hash",
        "chunk_index": 0,
    }

    collection.add(
        ids=["chunk-1"],
        documents=["       PROGRAM-ID. HELLO.\n"],
        embeddings=[[1.0, 0.0, 0.0]],
        metadatas=[metadata],
    )

    result = collection.get(
        ids=["chunk-1"],
        include=["documents", "metadatas"],
    )

    assert result["ids"] == ["chunk-1"]
    assert result["documents"] == ["       PROGRAM-ID. HELLO.\n"]
    assert result["metadatas"] == [metadata]


def test_chroma_chunk_store_upserts_source_chunk(
    tmp_path: Path,
) -> None:
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"),
    )
    collection = client.create_collection(
        name="test-chunks",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    store = ChromaChunkStore(collection)

    chunk = SourceChunk(
        chunk_id="chunk-1",
        text="       PROGRAM-ID. HELLO.\n",
        source_path="samples/hello.cbl",
        language="cobol",
        symbol="HELLO",
        content_hash="test-content-hash",
        chunk_index=0,
    )

    store.upsert(
        [chunk],
        embeddings=[[1.0, 0.0, 0.0]],
    )

    result = collection.get(
        ids=[chunk.chunk_id],
        include=["documents", "metadatas"],
    )

    assert result["ids"] == [chunk.chunk_id]
    assert result["documents"] == [chunk.text]
    assert result["metadatas"] == [
        {
            "source_path": chunk.source_path,
            "language": chunk.language,
            "symbol": chunk.symbol,
            "content_hash": chunk.content_hash,
            "chunk_index": chunk.chunk_index,
        }
    ]


def test_chroma_chunk_store_replaces_changed_source(
    tmp_path: Path,
) -> None:
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"),
    )
    collection = client.create_collection(
        name="test-chunks",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    store = ChromaChunkStore(collection)

    old_chunk = SourceChunk(
        chunk_id="old-chunk",
        text="       PROGRAM-ID. HELLO.\n",
        source_path="samples/hello.cbl",
        language="cobol",
        symbol="HELLO",
        content_hash="old-content-hash",
        chunk_index=0,
    )
    store.upsert(
        [old_chunk],
        embeddings=[[1.0, 0.0, 0.0]],
    )

    new_chunk = SourceChunk(
        chunk_id="new-chunk",
        text="       PROGRAM-ID. HELLO-CHANGED.\n",
        source_path="samples/hello.cbl",
        language="cobol",
        symbol="HELLO-CHANGED",
        content_hash="new-content-hash",
        chunk_index=0,
    )

    store.replace_source(
        source_path=new_chunk.source_path,
        chunks=[new_chunk],
        embeddings=[[0.0, 1.0, 0.0]],
    )

    result = collection.get(
        include=["documents", "metadatas"],
    )

    assert result["ids"] == [new_chunk.chunk_id]
    assert result["documents"] == [new_chunk.text]
    assert result["metadatas"] == [
        {
            "source_path": new_chunk.source_path,
            "language": new_chunk.language,
            "symbol": new_chunk.symbol,
            "content_hash": new_chunk.content_hash,
            "chunk_index": new_chunk.chunk_index,
        }
    ]


def test_chroma_chunk_store_rebuild_replaces_all_chunks(
    tmp_path: Path,
) -> None:
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"),
    )
    collection = client.create_collection(
        name="test-chunks",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    store = ChromaChunkStore(collection)

    old_chunks = [
        SourceChunk(
            chunk_id="old-a",
            text="       PROGRAM-ID. OLD-A.\n",
            source_path="samples/old-a.cbl",
            language="cobol",
            symbol="OLD-A",
            content_hash="old-hash-a",
            chunk_index=0,
        ),
        SourceChunk(
            chunk_id="old-b",
            text="       PROGRAM-ID. OLD-B.\n",
            source_path="samples/old-b.cbl",
            language="cobol",
            symbol="OLD-B",
            content_hash="old-hash-b",
            chunk_index=0,
        ),
    ]
    store.upsert(
        old_chunks,
        embeddings=[
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
    )

    new_chunk = SourceChunk(
        chunk_id="new-chunk",
        text="       PROGRAM-ID. NEW.\n",
        source_path="samples/new.cbl",
        language="cobol",
        symbol="NEW",
        content_hash="new-hash",
        chunk_index=0,
    )

    store.rebuild(
        [new_chunk],
        embeddings=[[0.0, 0.0, 1.0]],
    )

    result = collection.get(
        include=["documents", "metadatas"],
    )

    assert result["ids"] == [new_chunk.chunk_id]
    assert result["documents"] == [new_chunk.text]
    assert collection.count() == 1


def test_chroma_chunk_store_search_returns_metadata_and_score(
    tmp_path: Path,
) -> None:
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"),
    )
    collection = client.create_collection(
        name="test-chunks",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    store = ChromaChunkStore(collection)

    target = SourceChunk(
        chunk_id="target-chunk",
        text="       PROGRAM-ID. TARGET.\n",
        source_path="samples/target.cbl",
        language="cobol",
        symbol="TARGET",
        content_hash="target-hash",
        chunk_index=0,
    )
    other = SourceChunk(
        chunk_id="other-chunk",
        text="       PROGRAM-ID. OTHER.\n",
        source_path="samples/other.cbl",
        language="cobol",
        symbol="OTHER",
        content_hash="other-hash",
        chunk_index=0,
    )

    store.upsert(
        [target, other],
        embeddings=[
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
    )

    results = store.search(
        query_embedding=[1.0, 0.0, 0.0],
        limit=1,
    )

    assert len(results) == 1

    result = results[0]
    assert result.chunk_id == target.chunk_id
    assert result.text == target.text
    assert result.source_path == target.source_path
    assert result.symbol == target.symbol
    assert result.score == pytest.approx(1.0)


def test_chroma_chunk_store_search_applies_metadata_filter(tmp_path: Path) -> None:
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = client.create_collection(
        name="filtered-chunks",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    store = ChromaChunkStore(collection)
    cobol_chunk = SourceChunk(
        chunk_id="cobol-chunk",
        text="COBOL",
        source_path="samples/program.cbl",
        language="cobol",
        symbol="PROGRAM",
        content_hash="cobol-hash",
        chunk_index=0,
    )
    java_chunk = SourceChunk(
        chunk_id="java-chunk",
        text="JAVA",
        source_path="samples/Program.java",
        language="java",
        symbol="Program",
        content_hash="java-hash",
        chunk_index=0,
    )
    store.upsert(
        [cobol_chunk, java_chunk],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
    )

    results = store.search(
        query_embedding=[0.0, 1.0],
        limit=2,
        where={"language": "cobol"},
    )

    assert [result.chunk_id for result in results] == ["cobol-chunk"]
