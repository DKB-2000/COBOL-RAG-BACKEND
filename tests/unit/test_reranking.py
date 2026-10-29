from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from legacy_rag.retrieval.chroma_store import SearchResult
from legacy_rag.retrieval.reranking import ContextSearcher, LocalBgeReranker, RerankedSearcher


def result(index, text="code"):
    return SearchResult(str(index), text, "samples/demo.cbl", "cobol", "MAIN", "hash", index, .5)


class Searcher:
    def __init__(self, results):
        self.results = results
        self.limits = []

    def search(self, *, query, limit):
        self.limits.append(limit)
        return self.results[:limit]


class ReverseRanker:
    def rank(self, query, candidates):
        return list(reversed(candidates))


def test_reranks_30_candidates_before_applying_response_limit():
    source = Searcher([result(i) for i in range(40)])
    searcher = RerankedSearcher(source, ReverseRanker())
    rows = searcher.search(query="question", limit=2)
    assert [r.chunk_id for r in rows] == ["29", "28"]
    assert source.limits == [30]
    assert rows[0] == source.results[29]  # Original text, metadata and cosine score.


def test_search_limits_above_candidate_floor_are_preserved():
    source = Searcher([result(i) for i in range(50)])
    assert len(RerankedSearcher(source, ReverseRanker()).search(query="q", limit=50)) == 50
    assert source.limits == [50]


def test_context_uses_later_candidates_when_high_ranked_chunk_exceeds_budget():
    source = Searcher([replace(result(0), text="x" * 4001)] + [result(i) for i in range(1, 30)])
    rows = ContextSearcher(source).search(query="q", limit=10)
    assert [r.chunk_id for r in rows] == [str(i) for i in range(1, 11)]
    assert source.limits == [30]


def test_context_respects_requested_count_and_character_budget():
    source = Searcher([result(i, "x" * 2100) for i in range(30)])
    rows = ContextSearcher(source).search(query="q", limit=2)
    assert len(rows) == 1
    assert sum(len(r.text) for r in rows) <= 4000


def test_empty_search_does_not_call_ranker():
    class UnavailableRanker:
        def rank(self, *args):
            raise AssertionError("must not load a model for an empty index")

    assert RerankedSearcher(Searcher([]), UnavailableRanker()).search(query="q", limit=5) == []


def mock_runtime(monkeypatch, tmp_path, scores):
    import sys

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    ranker = LocalBgeReranker(tmp_path)

    def tokenize(pairs, **kwargs):
        if not kwargs.get("return_tensors"):
            return {"input_ids": [[0] * len(passage) for _, passage in pairs]}
        assert kwargs["max_length"] == 512
        return {"pairs": pairs}

    class Logits:
        def __init__(self, values):
            self.values = values

        def view(self, *_):
            return self

        def float(self):
            return self

        def tolist(self):
            return self.values

    def model(*, pairs, return_dict):
        assert return_dict
        return SimpleNamespace(logits=Logits([scores[passage.split("\n\n")[1]]
                                              for _, passage in pairs]))

    ranker._model = model
    ranker._tokenizer = tokenize
    return ranker


def test_length_batching_maps_scores_back_and_ties_keep_retrieval_order(monkeypatch, tmp_path):
    texts = ["longest", "a", "middle", "bb", "ccc"]
    ranker = mock_runtime(monkeypatch, tmp_path, dict(zip(texts, [1, 1, 3, 0, 2])))
    ranked = ranker.rank("q", [result(i, text) for i, text in enumerate(texts)])
    assert [r.chunk_id for r in ranked] == ["2", "4", "0", "1", "3"]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_invalid_scores_fail_instead_of_silently_falling_back(monkeypatch, tmp_path, value):
    ranker = mock_runtime(monkeypatch, tmp_path, {"code": value})
    with pytest.raises(RuntimeError, match="Invalid reranker scores"):
        ranker.rank("q", [result(0)])
