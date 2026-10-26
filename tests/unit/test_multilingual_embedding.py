import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from legacy_rag.evaluation.multilingual_embedding import (
    MultilingualOnnxEmbedding,
    masked_mean_pool,
)


def test_pooling_excludes_padding_and_normalizes_vectors() -> None:
    tokens = np.array([[[3.0, 0.0], [0.0, 4.0], [100.0, 100.0]]], dtype=np.float32)
    actual = masked_mean_pool(tokens, np.array([[1, 1, 0]]))
    np.testing.assert_allclose(actual, [[0.6, 0.8]], atol=1e-6)
    np.testing.assert_array_equal(masked_mean_pool(tokens, np.zeros((1, 3))), [[0.0, 0.0]])


def test_encoder_truncates_batches_and_preserves_untruncated_token_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = Tokenizer(
        models.WordLevel(
            {"<pad>": 1, "[UNK]": 0, "hello": 2, "[CLS]": 3, "[SEP]": 4}, unk_token="[UNK]"
        )
    )
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        special_tokens=[("[CLS]", 3), ("[SEP]", 4)],
    )
    tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    (tmp_path / "sentence_bert_config.json").write_text(
        json.dumps({"max_seq_length": 128}),
        encoding="utf-8",
    )
    (tmp_path / "1_Pooling").mkdir()
    (tmp_path / "1_Pooling" / "config.json").write_text(
        json.dumps(
            {
                "pooling_mode_mean_tokens": True,
                "pooling_mode_cls_token": False,
                "pooling_mode_max_tokens": False,
                "pooling_mode_mean_sqrt_len_tokens": False,
            }
        ),
        encoding="utf-8",
    )
    feeds = []

    class FakeSession:
        def get_inputs(self):
            return [
                SimpleNamespace(name=name)
                for name in ("input_ids", "attention_mask", "token_type_ids")
            ]

        def run(self, names, feed):
            feeds.append(feed)
            return [np.ones((*feed["input_ids"].shape, 384), dtype=np.float32)]

    def make_session(*args, **kwargs):
        assert kwargs["providers"] == ["CPUExecutionProvider"]
        return FakeSession()

    monkeypatch.setattr(
        "legacy_rag.evaluation.multilingual_embedding.ort.InferenceSession", make_session
    )
    encoder = MultilingualOnnxEmbedding(tmp_path)
    texts = ["hello " * 140] + ["hello"] * 18
    assert encoder.token_lengths(texts) == [142] + [3] * 18
    result = encoder(texts)
    assert np.asarray(result).shape == (19, 384)
    np.testing.assert_allclose(np.linalg.norm(result, axis=1), np.ones(19), atol=1e-6)
    assert feeds[0]["input_ids"].shape == (16, 128)
    assert feeds[1]["input_ids"].shape == (3, 3)
    assert feeds[0]["attention_mask"][1].sum() == 3
    assert feeds[0]["input_ids"][1, 3] == 1
    assert encoder.token_lengths(texts) == [142] + [3] * 18
    assert encoder([]) == []
