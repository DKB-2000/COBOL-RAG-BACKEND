from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from legacy_rag.api.dependencies import get_chunk_searcher
from legacy_rag.api.services import ChunkSearcher

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse, summary="Check service health")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


class ReadinessResponse(BaseModel):
    status: Literal["ready"]


@router.get("/ready", response_model=ReadinessResponse, summary="Check retrieval readiness")
def ready(searcher: Annotated[ChunkSearcher, Depends(get_chunk_searcher)]) -> ReadinessResponse:
    if not searcher.search(query="readiness", limit=1):
        raise HTTPException(status_code=503, detail="index_empty")
    return ReadinessResponse(status="ready")
