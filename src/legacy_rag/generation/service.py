from typing import Protocol

from legacy_rag.generation.models import GeneratedAnswer, GenerationModel, QueryResult
from legacy_rag.generation.prompt import build_generation_request
from legacy_rag.retrieval.chroma_store import SearchResult
from legacy_rag.retrieval.context import assemble_context


class QuerySearcher(Protocol):
    def search(self, *, query: str, limit: int) -> list[SearchResult]: ...


class GroundedQueryService:
    def __init__(self, *, searcher: QuerySearcher, model: GenerationModel | None) -> None:
        self._searcher = searcher
        self._model = model

    def query(self, *, query: str, limit: int = 10) -> QueryResult:
        sources = assemble_context(self._searcher.search(query=query, limit=limit))
        if not sources:
            return QueryResult(status="refused", reason="no_evidence")
        if self._model is None:
            return QueryResult(status="unavailable", reason="generation_unavailable")
        try:
            output = self._model.generate(build_generation_request(query, sources))
            # Revalidate even model instances: adapters must not bypass the output contract.
            output = GeneratedAnswer.model_validate(output.model_dump())
        except Exception:  # noqa: BLE001 -- isolate arbitrary provider errors at this boundary
            # Provider exception messages may contain prompts, credentials or source code.
            return QueryResult(status="unavailable", reason="generation_unavailable")
        if output.status == "refused":
            return QueryResult(status="refused", reason=output.reason)
        allowed_ids = {source.chunk_id for source in sources}
        if any(
            not claim.chunk_ids or not set(claim.chunk_ids) <= allowed_ids
            for claim in output.claims
        ):
            return QueryResult(status="refused", reason="invalid_citations")
        cited_ids = {chunk_id for claim in output.claims for chunk_id in claim.chunk_ids}
        return QueryResult(
            status="answered",
            answer="\n".join(
                f"{claim.text} " + " ".join(f"[{chunk_id}]" for chunk_id in claim.chunk_ids)
                for claim in output.claims
            ),
            claims=tuple(output.claims),
            sources=tuple(source for source in sources if source.chunk_id in cited_ids),
        )
