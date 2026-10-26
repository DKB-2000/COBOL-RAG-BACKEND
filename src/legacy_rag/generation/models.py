from dataclasses import dataclass
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from legacy_rag.retrieval.chroma_store import SearchResult


class AnswerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1)
    chunk_ids: list[str]


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "refused"]
    claims: list[AnswerClaim] = Field(default_factory=list)
    reason: Literal["insufficient_evidence", "conflicting_evidence"] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "answered" and (not self.claims or self.reason is not None):
            raise ValueError("answered output requires claims and no refusal reason")
        if self.status == "refused" and (self.claims or self.reason is None):
            raise ValueError("refused output requires a reason and no claims")
        return self


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    system_prompt: str
    user_prompt: str


class GenerationModel(Protocol):
    def generate(self, request: GenerationRequest) -> GeneratedAnswer: ...


QueryStatus = Literal["answered", "refused", "unavailable"]
QueryReason = Literal[
    "no_evidence", "insufficient_evidence", "conflicting_evidence",
    "invalid_citations", "generation_unavailable",
]


@dataclass(frozen=True, slots=True)
class QueryResult:
    status: QueryStatus
    answer: str | None = None
    reason: QueryReason | None = None
    claims: tuple[AnswerClaim, ...] = ()
    sources: tuple[SearchResult, ...] = ()
