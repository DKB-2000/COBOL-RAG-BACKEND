from dataclasses import asdict, replace
from pathlib import Path

import pytest

from legacy_rag.api import dependencies
from legacy_rag.api.public_corpus import (
    PUBLIC_SOURCE_HASHES,
    is_public_chunk,
    load_public_chunks,
)
from legacy_rag.api.services import StructuredDocumentIndexer
from legacy_rag.generation.openai_model import OpenAIGenerationModel
from legacy_rag.ingestion.loader import load_cobol_file
from legacy_rag.retrieval.chroma_store import SearchResult

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(autouse=True)
def isolated_generation_settings(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "disabled")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dependencies.get_generation_model.cache_clear()
    yield
    dependencies.get_generation_model.cache_clear()


def test_disabled_or_missing_key_never_constructs_provider(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("provider must not be initialized")

    monkeypatch.setattr(dependencies, "create_openai_model", forbidden)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    assert dependencies.get_generation_model() is None
    dependencies.get_generation_model.cache_clear()
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert dependencies.get_generation_model() is None


def test_provider_configuration_is_cached_and_key_is_redacted(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("LEGACY_RAG_OPENAI_TIMEOUT_SECONDS", "12")
    calls = []
    sentinel = object()

    def create(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(dependencies, "create_openai_model", create)
    assert dependencies.get_generation_model() is sentinel
    assert dependencies.get_generation_model() is sentinel
    assert len(calls) == 1
    assert calls[0] == {
        "api_key": "test-only-key", "model": "gpt-6-luna",
        "timeout_seconds": 12.0, "max_output_tokens": 1000,
    }
    assert "test-only-key" not in repr(dependencies.OpenAISettings())


@pytest.mark.parametrize("name,value", [
    ("LEGACY_RAG_OPENAI_TIMEOUT_SECONDS", "-1"),
    ("LEGACY_RAG_OPENAI_MAX_OUTPUT_TOKENS", "0"),
    ("LEGACY_RAG_OPENAI_MODEL", "unsupported-model"),
])
def test_bad_generation_configuration_does_not_invalidate_search_settings(monkeypatch, name, value):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv(name, value)
    assert dependencies.get_generation_model() is None
    assert dependencies.ApiSettings().generation_provider == "openai"


def test_provider_initialization_failure_returns_none_without_logging_key(monkeypatch, caplog):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")

    def fail(**kwargs):
        raise RuntimeError("test-only-key secret initialization data")

    monkeypatch.setattr(dependencies, "create_openai_model", fail)
    assert dependencies.get_generation_model() is None
    assert "test-only-key" not in caplog.text


def test_cached_client_is_closed_and_reset_on_shutdown(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    closed = []

    class Model:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(dependencies, "create_openai_model", lambda **kwargs: Model())
    dependencies.get_generation_model()
    dependencies.close_generation_model()
    assert closed == [True]
    assert dependencies.get_generation_model.cache_info().currsize == 0


def test_public_policy_checks_actual_chunk_text_not_only_metadata():
    approved = load_public_chunks(DATA_ROOT)
    assert len(approved) == 52
    chunk = next(iter(approved.values()))
    public = SearchResult(**asdict(chunk), score=0.5)
    assert is_public_chunk(public, approved)
    assert not is_public_chunk(replace(public, text="private text with forged public metadata"), approved)
    assert not is_public_chunk(replace(public, source_path="raw/local-evaluation/private.cbl"), approved)


def test_modified_public_file_is_excluded_by_whole_source_hash(tmp_path):
    source = tmp_path / "samples/account-balance.cbl"
    source.parent.mkdir()
    source.write_text("       PROGRAM-ID. ACCOUNT-BALANCE.\n", encoding="utf-8")
    assert load_public_chunks(tmp_path) == {}


def test_cached_openai_model_keeps_public_guard_even_if_provider_setting_changes():
    class PrivateSearcher:
        def search(self, *, query, limit):
            return [SearchResult(
                "private", "LOCAL-ONLY", "raw/private.cbl", "cobol", "PRIVATE", "h", 0, 0.5,
            )]

    # The client deliberately has no response method: it must never be called.
    model = OpenAIGenerationModel(client=object(), model="gpt-6-luna", max_output_tokens=1000)
    response = dependencies.get_query_service(PrivateSearcher(), model).query(query="?")
    assert response.status == "refused" and response.reason == "no_evidence"


@pytest.mark.parametrize("rebuild", [True, False])
def test_unapproved_index_input_fails_before_embedding_or_store_mutation(tmp_path, rebuild):
    source = tmp_path / "raw/private.cbl"
    source.parent.mkdir()
    source.write_text("       PROGRAM-ID. PRIVATE.\n", encoding="utf-8")

    def forbidden(texts):
        pytest.fail("unapproved input must not reach embeddings")

    indexer = StructuredDocumentIndexer(
        data_root=tmp_path, store=object(), embed_texts=forbidden,
        allowed_source_hashes=PUBLIC_SOURCE_HASHES,
    )
    with pytest.raises(ValueError, match="not approved"):
        indexer.index(source_paths=["raw/private.cbl"], rebuild=rebuild)


def test_public_sample_content_hash_matches_loader_contract():
    for path, digest in PUBLIC_SOURCE_HASHES.items():
        assert load_cobol_file(DATA_ROOT / path, data_root=DATA_ROOT).content_hash == digest


def test_openai_collection_is_separate_from_existing_search_collection(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "openai")
    captured = {}

    class Client:
        def get_or_create_collection(self, **kwargs):
            captured.update(kwargs)
            return object()

    monkeypatch.setattr(dependencies.chromadb, "PersistentClient", lambda **kwargs: Client())
    dependencies.get_chunk_store.cache_clear()
    try:
        dependencies.get_chunk_store()
        assert captured["name"] == "legacy-rag-openai-public-identifier-v1"
    finally:
        dependencies.get_chunk_store.cache_clear()
