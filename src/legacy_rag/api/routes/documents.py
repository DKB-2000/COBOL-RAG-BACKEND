from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from legacy_rag.api.dependencies import get_document_indexer
from legacy_rag.api.services import DocumentIndexer

router = APIRouter(prefix="/documents", tags=["documents"])


class IndexDocumentsRequest(BaseModel):
    source_paths: list[str] = Field(min_length=1)
    rebuild: bool = False


class IndexDocumentsResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int


@router.post("/index", response_model=IndexDocumentsResponse)
def index_documents(
    request: IndexDocumentsRequest,
    indexer: Annotated[DocumentIndexer, Depends(get_document_indexer)],
) -> IndexDocumentsResponse:
    try:
        result = indexer.index(
            source_paths=request.source_paths,
            rebuild=request.rebuild,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_source",
        ) from None

    return IndexDocumentsResponse(
        indexed_documents=result.indexed_documents,
        indexed_chunks=result.indexed_chunks,
    )
