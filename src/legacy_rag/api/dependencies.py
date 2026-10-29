from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

import chromadb
from chromadb.config import Settings as ChromaSettings
from fastapi import Depends
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES, is_public_chunk, load_public_chunks
from legacy_rag.api.services import (
    ChunkSearcher,
    DocumentIndexer,
    StructuredDocumentIndexer,
    VectorChunkSearcher,
)
from legacy_rag.generation.models import GenerationModel
from legacy_rag.generation.ollama_model import OllamaGenerationModel, create_ollama_model
from legacy_rag.generation.openai_model import OpenAIGenerationModel, create_openai_model
from legacy_rag.generation.service import GroundedQueryService
from legacy_rag.retrieval.chroma_store import ChromaChunkStore
from legacy_rag.retrieval.embedding import (
    MODEL_ID,
    MODEL_REVISION,
    IdentifierAwareOnnxEmbedding,
    MultilingualOnnxEmbedding,
)
from legacy_rag.retrieval.reranking import (
    RERANKER_ID,
    RERANKER_REVISION,
    ContextSearcher,
    LocalBgeReranker,
    RerankedSearcher,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_reranker_creation_lock = Lock()


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEGACY_RAG_")

    data_root: Path = _PROJECT_ROOT / "data"
    chroma_path: Path = _PROJECT_ROOT / "data" / "chroma" / "api-v3-identifier-aware"
    model_dir: Path = (
        _PROJECT_ROOT / "data" / "models" / ("models--" + MODEL_ID.replace("/", "--"))
        / "snapshots" / MODEL_REVISION
    )
    generation_provider: Literal["disabled", "openai", "ollama"] = "disabled"
    retrieval_profile: Literal["original", "identifier-aware"] = "identifier-aware"
    reranking: Literal["bge-int8", "disabled"] = "bge-int8"
    reranker_model_dir: Path = (
        _PROJECT_ROOT / "data" / "models" / ("models--" + RERANKER_ID.replace("/", "--"))
        / "snapshots" / RERANKER_REVISION
    )


class OpenAISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEGACY_RAG_")

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: Literal["gpt-6-luna"] = "gpt-6-luna"
    openai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    openai_max_output_tokens: int = Field(default=1000, ge=64, le=2048)


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEGACY_RAG_")

    ollama_timeout_seconds: float = Field(default=300.0, gt=0, le=600)
    ollama_max_output_tokens: int = Field(default=1024, ge=64, le=4096)


@lru_cache
def get_embedding_function() -> MultilingualOnnxEmbedding:
    settings = ApiSettings()
    encoder = (IdentifierAwareOnnxEmbedding if settings.retrieval_profile == "identifier-aware"
               else MultilingualOnnxEmbedding)
    return encoder(settings.model_dir.resolve())


@lru_cache
def get_chunk_store() -> ChromaChunkStore:
    settings = ApiSettings()
    client = chromadb.PersistentClient(
        path=str(settings.chroma_path.resolve()), settings=ChromaSettings(anonymized_telemetry=False),
    )
    if settings.retrieval_profile == "identifier-aware":
        name = ("legacy-rag-openai-public-identifier-v1"
                if settings.generation_provider == "openai" else "legacy-rag-api-v3-identifier-aware")
    else:
        name = ("legacy-rag-openai-public-v1" if settings.generation_provider == "openai"
                else "legacy-rag-api-v2-multilingual")
    collection = client.get_or_create_collection(
        name=name,
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    return ChromaChunkStore(collection)


@lru_cache
def get_document_indexer() -> DocumentIndexer:
    settings = ApiSettings()
    return StructuredDocumentIndexer(
        data_root=settings.data_root.resolve(),
        store=get_chunk_store(),
        embed_texts=get_embedding_function(),
        allowed_source_hashes=(
            PUBLIC_SOURCE_HASHES if settings.generation_provider == "openai" else None
        ),
    )


@lru_cache
def _get_reranker() -> LocalBgeReranker:
    return LocalBgeReranker(ApiSettings().reranker_model_dir.resolve())


@lru_cache
def get_chunk_searcher() -> ChunkSearcher:
    searcher = VectorChunkSearcher(
        store=get_chunk_store(),
        embed_texts=get_embedding_function(),
    )
    if ApiSettings().reranking == "disabled":
        return searcher
    # lru_cache alone permits concurrent misses; serialize the heavy model owner creation.
    with _reranker_creation_lock:
        ranker = _get_reranker()
    return RerankedSearcher(searcher, ranker)


@lru_cache
def get_generation_model() -> OpenAIGenerationModel | OllamaGenerationModel | None:
    provider = ApiSettings().generation_provider
    if provider == "disabled":
        return None
    try:
        if provider == "ollama":
            local_settings = OllamaSettings()
            return create_ollama_model(
                timeout_seconds=local_settings.ollama_timeout_seconds,
                max_output_tokens=local_settings.ollama_max_output_tokens,
            )
        settings = OpenAISettings()
        if not settings.openai_api_key:
            return None
        key = settings.openai_api_key.get_secret_value().strip()
        if not key:
            return None
        return create_openai_model(
            api_key=key, model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            max_output_tokens=settings.openai_max_output_tokens,
        )
    except Exception:  # noqa: BLE001 -- SDK/config errors must not expose credentials
        return None


def close_generation_model() -> None:
    if get_generation_model.cache_info().currsize:
        model = get_generation_model()
        try:
            if model is not None:
                model.close()
        finally:
            get_generation_model.cache_clear()


class PublicQuerySearcher:
    def __init__(self, searcher: ChunkSearcher, data_root: Path) -> None:
        self._searcher = searcher
        self._approved = load_public_chunks(data_root)

    def search(self, *, query: str, limit: int):
        return [
            source for source in self._searcher.search(query=query, limit=limit)
            if is_public_chunk(source, self._approved)
        ]


def get_query_service(
    searcher: Annotated[ChunkSearcher, Depends(get_chunk_searcher)],
    model: Annotated[GenerationModel | None, Depends(get_generation_model)],
) -> GroundedQueryService:
    settings = ApiSettings()
    if settings.generation_provider == "openai" or isinstance(model, OpenAIGenerationModel):
        searcher = PublicQuerySearcher(searcher, settings.data_root.resolve())
    if settings.reranking == "bge-int8":
        searcher = ContextSearcher(searcher)
    return GroundedQueryService(searcher=searcher, model=model)
