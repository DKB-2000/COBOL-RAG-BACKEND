from dataclasses import replace

import pytest

from legacy_rag.generation.models import AnswerClaim, GeneratedAnswer
from legacy_rag.generation.service import GroundedQueryService
from legacy_rag.retrieval.chroma_store import SearchResult
from legacy_rag.retrieval.context import assemble_context


def result(chunk_id="c1", text="MOVE 0 TO BALANCE."):
    return SearchResult(chunk_id, text, "samples/a.cbl", "cobol", "RESET", "hash", 0, 0.7)


class Searcher:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, *, query, limit):
        self.calls.append((query, limit))
        return self.results


class Model:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.output


def test_context_preserves_rank_and_whole_text_with_dedup_and_budget():
    first = result(text="abc")
    selected = assemble_context(
        [first, first, result("large", "123456"), result("last", "xy")],
        max_chars=5,
        max_chunks=10,
    )
    assert selected == (first, result("last", "xy"))
    assert assemble_context([first, result("last")], max_chunks=1) == (first,)
    assert assemble_context([result(text=" " * 5)]) == ()


def test_query_connects_claims_to_only_selected_sources_and_keeps_question_as_data():
    searcher = Searcher([result(), result("unused")])
    model = Model(GeneratedAnswer(
        status="answered", claims=[AnswerClaim(text="잔액을 0으로 초기화한다.", chunk_ids=["c1"])]
    ))
    response = GroundedQueryService(searcher=searcher, model=model).query(query="초기화?", limit=10)
    assert response.status == "answered"
    assert response.reason is None
    assert response.claims[0].chunk_ids == ["c1"]
    assert response.answer == "잔액을 0으로 초기화한다. [c1]"
    assert response.sources == (result(),)
    assert searcher.calls == [("초기화?", 10)]
    request = model.requests[0]
    assert "insufficient_evidence" in request.system_prompt
    assert "conflicting_evidence" in request.system_prompt
    assert '"question": "초기화?"' in request.user_prompt
    assert "MOVE 0 TO BALANCE." in request.user_prompt


@pytest.mark.parametrize("results", [[], [result(text="x" * 4001)]])
def test_no_usable_evidence_does_not_call_model(results):
    model = Model()
    response = GroundedQueryService(searcher=Searcher(results), model=model).query(query="?", limit=10)
    assert response.status == "refused"
    assert response.reason == "no_evidence"
    assert response.answer is None and response.claims == () and response.sources == ()
    assert model.requests == []


@pytest.mark.parametrize("reason", ["insufficient_evidence", "conflicting_evidence"])
def test_model_can_refuse_without_exposing_generated_answer(reason):
    model = Model(GeneratedAnswer(status="refused", reason=reason))
    response = GroundedQueryService(searcher=Searcher([result()]), model=model).query(query="?", limit=10)
    assert response.status == "refused" and response.reason == reason
    assert response.answer is None and response.sources == ()


@pytest.mark.parametrize("ids", [[], ["not-retrieved"], ["c1", "unknown"]])
def test_uncited_or_unknown_citations_fail_closed(ids):
    model = Model(GeneratedAnswer(status="answered", claims=[AnswerClaim(text="claim", chunk_ids=ids)]))
    response = GroundedQueryService(searcher=Searcher([result()]), model=model).query(query="?", limit=10)
    assert response.status == "refused" and response.reason == "invalid_citations"
    assert response.answer is None and response.sources == ()


def test_cannot_cite_chunk_excluded_by_context_budget():
    model = Model(GeneratedAnswer(status="answered", claims=[AnswerClaim(text="claim", chunk_ids=["c2"])]))
    response = GroundedQueryService(
        searcher=Searcher([result(text="x" * 3999), result("c2", "yy")]), model=model
    ).query(query="?", limit=10)
    assert response.reason == "invalid_citations"
    assert '"chunk_id": "c2"' not in model.requests[0].user_prompt


@pytest.mark.parametrize("model", [None, Model(error=RuntimeError("secret-token"))])
def test_missing_or_failing_model_is_unavailable(model):
    response = GroundedQueryService(searcher=Searcher([result()]), model=model).query(query="?", limit=10)
    assert response.status == "unavailable" and response.reason == "generation_unavailable"
    assert response.answer is None and response.sources == ()


def test_blank_claim_and_empty_answer_are_not_accepted():
    with pytest.raises(ValueError):
        AnswerClaim(text="  ", chunk_ids=["c1"])
    with pytest.raises(ValueError):
        GeneratedAnswer(status="answered")
    with pytest.raises(ValueError):
        GeneratedAnswer(status="refused", reason="insufficient_evidence", claims=[
            AnswerClaim(text="claim", chunk_ids=["c1"])
        ])


def test_malformed_model_output_is_not_returned_as_an_answer():
    model = Model({"status": "answered", "answer": "uncited secret"})
    response = GroundedQueryService(searcher=Searcher([result()]), model=model).query(query="?", limit=10)
    assert response.status == "unavailable"
    assert response.answer is None


def test_max_context_chunks_is_ten_even_if_searcher_ignores_limit():
    sources = [replace(result(str(index)), chunk_index=index) for index in range(12)]
    assert len(assemble_context(sources)) == 10
