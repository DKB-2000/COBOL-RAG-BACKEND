from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, StringConstraints

from legacy_rag.api.dependencies import get_query_service
from legacy_rag.generation.models import AnswerClaim, QueryReason, QueryStatus
from legacy_rag.generation.service import GroundedQueryService

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    limit: int = Field(default=10, ge=1, le=10)


class QuerySourceResponse(BaseModel):
    chunk_id: str
    source_path: str
    language: str
    symbol: str
    chunk_index: int
    score: float


class QueryResponse(BaseModel):
    status: QueryStatus
    answer: str | None
    reason: QueryReason | None
    claims: list[AnswerClaim]
    sources: list[QuerySourceResponse]


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    service: Annotated[GroundedQueryService, Depends(get_query_service)],
    http_request: Request,
) -> QueryResponse:
    result = service.query(query=request.query, limit=request.limit)
    http_request.state.query_status = result.status
    return QueryResponse(
        status=result.status,
        answer=result.answer,
        reason=result.reason,
        claims=list(result.claims),
        sources=[
            QuerySourceResponse(
                chunk_id=source.chunk_id,
                source_path=source.source_path,
                language=source.language,
                symbol=source.symbol,
                chunk_index=source.chunk_index,
                score=source.score,
            )
            for source in result.sources
        ],
    )
