import pytest

from legacy_rag.api import dependencies


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "disabled")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dependencies.get_generation_model.cache_clear()
    yield
    dependencies.get_generation_model.cache_clear()


def test_ollama_is_opt_in_and_cached_without_openai_key(monkeypatch):
    calls = []
    sentinel = object()

    def create(**kwargs):
        calls.append(kwargs)
        return sentinel

    def forbidden(**kwargs):
        pytest.fail("OpenAI must not be initialized")

    monkeypatch.setattr(dependencies, "create_ollama_model", create)
    monkeypatch.setattr(dependencies, "create_openai_model", forbidden)
    assert dependencies.get_generation_model() is None
    assert calls == []
    dependencies.get_generation_model.cache_clear()
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "ollama")
    assert dependencies.get_generation_model() is sentinel
    assert dependencies.get_generation_model() is sentinel
    assert calls == [{"timeout_seconds": 300.0, "max_output_tokens": 1024}]


@pytest.mark.parametrize("name,value", [
    ("LEGACY_RAG_OLLAMA_TIMEOUT_SECONDS", "0"),
    ("LEGACY_RAG_OLLAMA_MAX_OUTPUT_TOKENS", "0"),
])
def test_bad_settings_fail_closed_without_breaking_search(monkeypatch, name, value):
    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "ollama")
    monkeypatch.setenv(name, value)
    assert dependencies.get_generation_model() is None
    assert dependencies.ApiSettings().generation_provider == "ollama"


def test_cached_client_is_closed_and_reset(monkeypatch):
    closed = []

    class Model:
        def close(self):
            closed.append(True)

    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "ollama")
    monkeypatch.setattr(dependencies, "create_ollama_model", lambda **kwargs: Model())
    dependencies.get_generation_model()
    dependencies.close_generation_model()
    assert closed == [True]
    assert dependencies.get_generation_model.cache_info().currsize == 0


@pytest.mark.parametrize("profile,collection", [
    ("identifier-aware", "legacy-rag-api-v3-identifier-aware"),
    ("original", "legacy-rag-api-v2-multilingual"),
])
def test_ollama_reuses_existing_search_collection(monkeypatch, profile, collection):
    names = []

    class Client:
        def get_or_create_collection(self, **kwargs):
            names.append(kwargs["name"])
            return object()

    monkeypatch.setenv("LEGACY_RAG_GENERATION_PROVIDER", "ollama")
    monkeypatch.setenv("LEGACY_RAG_RETRIEVAL_PROFILE", profile)
    monkeypatch.setattr(dependencies.chromadb, "PersistentClient", lambda **kwargs: Client())
    dependencies.get_chunk_store.cache_clear()
    try:
        dependencies.get_chunk_store()
        assert names == [collection]
    finally:
        dependencies.get_chunk_store.cache_clear()
