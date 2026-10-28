import pytest

from legacy_rag.retrieval.embedding import IdentifierAwareOnnxEmbedding, MultilingualOnnxEmbedding
from legacy_rag.retrieval.embedding_input import normalize_code_embedding_text


def test_identifier_words_are_normalized_without_changing_numeric_literals():
    assert normalize_code_embedding_text("WS-INDEX PIC 99 VALUE -1. 2026-10-27") == (
        "ws index pic 99 value -1. 2026-10-27"
    )
    assert normalize_code_embedding_text("APPLY-TRANSACTION에서 LK_RESULT_CODE는?") == (
        "apply transaction에서 lk result code는?"
    )


def test_same_normalization_applies_to_document_and_query_inputs(monkeypatch):
    captured = []

    def embed(self, texts):
        captured.append(texts)
        return [[1.0, 0.0] if len(captured) == 1 else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(MultilingualOnnxEmbedding, "__call__", embed)
    encoder = IdentifierAwareOnnxEmbedding.__new__(IdentifierAwareOnnxEmbedding)
    texts = ["Symbol: APPLY-WITHDRAWAL\nMOVE WS-AMOUNT", "출금 APPLY-WITHDRAWAL?"]
    for vector in encoder(texts):
        assert vector == pytest.approx([2 ** -0.5, 2 ** -0.5])
    assert captured == [texts, ["symbol: apply withdrawal\nmove ws amount", "출금 apply withdrawal?"]]
    assert texts[0] == "Symbol: APPLY-WITHDRAWAL\nMOVE WS-AMOUNT"


def test_unchanged_korean_query_does_not_repeat_inference(monkeypatch):
    captured = []

    def embed(self, texts):
        captured.append(texts)
        return [[1.0, 0.0]]

    monkeypatch.setattr(MultilingualOnnxEmbedding, "__call__", embed)
    encoder = IdentifierAwareOnnxEmbedding.__new__(IdentifierAwareOnnxEmbedding)
    assert encoder(["잔액을 계산하는 문단은?"]) == [[1.0, 0.0]]
    assert captured == [["잔액을 계산하는 문단은?"]]


def test_empty_batch_never_invokes_model(monkeypatch):
    def forbidden(self, texts):
        pytest.fail("empty input must not invoke ONNX")

    monkeypatch.setattr(MultilingualOnnxEmbedding, "__call__", forbidden)
    encoder = IdentifierAwareOnnxEmbedding.__new__(IdentifierAwareOnnxEmbedding)
    assert encoder([]) == []
