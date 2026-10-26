from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from legacy_rag.api.dependencies import get_chunk_searcher
from legacy_rag.api.services import ChunkSearcher

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class SearchResultResponse(BaseModel):
    chunk_id: str
    text: str
    source_path: str
    language: str
    symbol: str
    chunk_index: int
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultResponse]


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest,
    searcher: Annotated[ChunkSearcher, Depends(get_chunk_searcher)],
) -> SearchResponse:
    results = searcher.search(query=request.query, limit=request.limit)
    return SearchResponse(
        results=[
            SearchResultResponse(
                chunk_id=result.chunk_id,
                text=result.text,
                source_path=result.source_path,
                language=result.language,
                symbol=result.symbol,
                chunk_index=result.chunk_index,
                score=result.score,
            )
            for result in results
        ]
    )
