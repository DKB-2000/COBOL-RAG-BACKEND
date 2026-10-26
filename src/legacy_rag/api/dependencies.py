from functools import lru_cache
from pathlib import Path
from typing import Annotated

import chromadb
from fastapi import Depends
from pydantic_settings import BaseSettings, SettingsConfigDict

from legacy_rag.api.services import (
    ChunkSearcher,
    DocumentIndexer,
    StructuredDocumentIndexer,
    VectorChunkSearcher,
)
from legacy_rag.generation.models import GenerationModel
from legacy_rag.generation.service import GroundedQueryService
from legacy_rag.retrieval.chroma_store import ChromaChunkStore
from legacy_rag.retrieval.embedding import MODEL_ID, MODEL_REVISION, MultilingualOnnxEmbedding

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEGACY_RAG_")

    data_root: Path = _PROJECT_ROOT / "data"
    chroma_path: Path = _PROJECT_ROOT / "data" / "chroma" / "api-v2-multilingual"
    model_dir: Path = (
        _PROJECT_ROOT / "data" / "models" / ("models--" + MODEL_ID.replace("/", "--"))
        / "snapshots" / MODEL_REVISION
    )


@lru_cache
def get_embedding_function() -> MultilingualOnnxEmbedding:
    return MultilingualOnnxEmbedding(ApiSettings().model_dir.resolve())


@lru_cache
def get_chunk_store() -> ChromaChunkStore:
    settings = ApiSettings()
    client = chromadb.PersistentClient(path=str(settings.chroma_path.resolve()))
    collection = client.get_or_create_collection(
        name="legacy-rag-api-v2-multilingual",
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
    )


@lru_cache
def get_chunk_searcher() -> ChunkSearcher:
    return VectorChunkSearcher(
        store=get_chunk_store(),
        embed_texts=get_embedding_function(),
    )


def get_generation_model() -> GenerationModel | None:
    return None


def get_query_service(
    searcher: Annotated[ChunkSearcher, Depends(get_chunk_searcher)],
    model: Annotated[GenerationModel | None, Depends(get_generation_model)],
) -> GroundedQueryService:
    return GroundedQueryService(searcher=searcher, model=model)
