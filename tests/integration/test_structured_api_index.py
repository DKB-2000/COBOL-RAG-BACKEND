from pathlib import Path

import chromadb
import pytest

from legacy_rag.api import dependencies
from legacy_rag.api.services import StructuredDocumentIndexer, VectorChunkSearcher
from legacy_rag.ingestion.chunker import chunk_cobol_structure
from legacy_rag.ingestion.loader import load_cobol_files
from legacy_rag.retrieval.chroma_store import ChromaChunkStore
from legacy_rag.retrieval.embedding_input import build_contextual_embedding_text


def test_structured_index_embeds_context_but_persists_original_and_replaces(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    source = samples / "a.cbl"
    source.write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. A.\n"
        "       PROCEDURE DIVISION.\n       RESET.\n           MOVE 0 TO X.\n",
        encoding="utf-8",
    )
    inputs = []

    def embed(texts):
        inputs.append(texts)
        return [[1.0, 0.0] for _ in texts]

    collection = chromadb.PersistentClient(path=str(tmp_path / "index")).get_or_create_collection(
        "test-api-structured", embedding_function=None, configuration={"hnsw": {"space": "cosine"}},
    )
    store = ChromaChunkStore(collection)
    indexer = StructuredDocumentIndexer(data_root=tmp_path, store=store, embed_texts=embed)
    outcome = indexer.index(source_paths=["samples/a.cbl"], rebuild=True)
    expected = chunk_cobol_structure(load_cobol_files([source], data_root=tmp_path)[0])
    assert outcome.indexed_chunks == len(expected) == 3
    assert inputs[0] == [build_contextual_embedding_text(chunk) for chunk in expected]
    raw = collection.get(include=["documents", "metadatas"])
    by_id = {chunk.chunk_id: chunk for chunk in expected}
    for chunk_id, text, metadata in zip(raw["ids"], raw["documents"], raw["metadatas"]):
        assert text == by_id[chunk_id].text
        assert metadata["source_path"] == "samples/a.cbl"
    searcher = VectorChunkSearcher(store=store, embed_texts=embed)
    assert len(searcher.search(query="초기화?", limit=10)) == 3
    assert inputs[-1] == ["초기화?"]
    old_ids = set(raw["ids"])
    source.write_text("       PROGRAM-ID. A.\n", encoding="utf-8")
    outcome = indexer.index(source_paths=["samples/a.cbl"], rebuild=False)
    assert outcome.indexed_chunks == 1
    assert collection.count() == 1
    assert not old_ids.intersection(collection.get(include=[])["ids"])


def test_embedding_failure_does_not_replace_existing_index(tmp_path):
    source = tmp_path / "a.cbl"
    source.write_text("       PROGRAM-ID. A.\n", encoding="utf-8")
    writes = []

    class Store:
        def rebuild(self, *args, **kwargs):
            writes.append("rebuild")

        def replace_source(self, **kwargs):
            writes.append("replace")

    def fail(texts):
        raise RuntimeError("encoder failed")

    indexer = StructuredDocumentIndexer(data_root=tmp_path, store=Store(), embed_texts=fail)
    for rebuild in (True, False):
        with pytest.raises(RuntimeError):
            indexer.index(source_paths=["a.cbl"], rebuild=rebuild)
    assert writes == []


def test_default_dependencies_use_local_model_and_isolated_collection(monkeypatch):
    settings = dependencies.ApiSettings()
    assert settings.chroma_path.name == "api-v3-identifier-aware"
    assert settings.retrieval_profile == "identifier-aware"
    assert settings.model_dir.name == "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    captured = {}

    class Client:
        def get_or_create_collection(self, **kwargs):
            captured.update(kwargs)
            return object()

    monkeypatch.setattr(dependencies.chromadb, "PersistentClient", lambda **kwargs: Client())
    dependencies.get_chunk_store.cache_clear()
    try:
        dependencies.get_chunk_store()
        assert captured["name"] == "legacy-rag-api-v3-identifier-aware"
        assert captured["embedding_function"] is None
        assert captured["configuration"] == {"hnsw": {"space": "cosine"}}
    finally:
        dependencies.get_chunk_store.cache_clear()


def test_api_embedding_dependency_uses_only_configured_local_files(monkeypatch):
    model_dir = Path("local-model")
    monkeypatch.setenv("LEGACY_RAG_MODEL_DIR", str(model_dir))
    captured = []
    monkeypatch.setattr(dependencies, "IdentifierAwareOnnxEmbedding", lambda path: captured.append(path))
    dependencies.get_embedding_function.cache_clear()
    try:
        dependencies.get_embedding_function()
        assert captured == [model_dir.resolve()]
    finally:
        dependencies.get_embedding_function.cache_clear()


def test_original_profile_keeps_old_encoder_and_collection(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_RETRIEVAL_PROFILE", "original")
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    captured = {}

    class Client:
        def get_or_create_collection(self, **kwargs):
            captured.update(kwargs)
            return object()

    monkeypatch.setattr(dependencies.chromadb, "PersistentClient", lambda **kwargs: Client())
    paths = []
    monkeypatch.setattr(dependencies, "MultilingualOnnxEmbedding", lambda path: paths.append(path))
    dependencies.get_chunk_store.cache_clear()
    dependencies.get_embedding_function.cache_clear()
    try:
        dependencies.get_chunk_store()
        dependencies.get_embedding_function()
        assert captured["name"] == "legacy-rag-openai-public-v1"
        assert len(paths) == 1
    finally:
        dependencies.get_chunk_store.cache_clear()
        dependencies.get_embedding_function.cache_clear()
