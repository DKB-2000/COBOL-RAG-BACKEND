from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from legacy_rag.evaluation.multilingual_embedding import (
    MultilingualOnnxEmbedding,
    WindowedMultilingualOnnxEmbedding,
)


def encoder_fixture(cls):
    encoder = object.__new__(cls)
    encoder.max_length = 128
    encoder.tokenizer = Tokenizer(
        models.WordLevel(
            {"[UNK]": 0, "<pad>": 1, "head": 2, "[CLS]": 3, "[SEP]": 4, "tail": 5},
            unk_token="[UNK]",
        )
    )
    encoder.tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    encoder.tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        special_tokens=[("[CLS]", 3), ("[SEP]", 4)],
    )
    encoder.tokenizer.enable_truncation(max_length=128)
    encoder.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
    feeds = []

    class Session:
        def get_inputs(self):
            return [
                SimpleNamespace(name=name)
                for name in ("input_ids", "attention_mask", "token_type_ids")
            ]

        def run(self, names, feed):
            feeds.append(feed)
            ids = feed["input_ids"]
            tokens = np.zeros((*ids.shape, 2), dtype=np.float32)
            tokens[:, :, 0] = ids == 2
            tokens[:, :, 1] = (ids == 5) * 100
            return [tokens]

    encoder.session = Session()
    return encoder, feeds


def test_windows_cover_every_payload_token_with_overlap_and_special_tokens() -> None:
    encoder, _ = encoder_fixture(WindowedMultilingualOnnxEmbedding)
    text = "head " * 280 + "tail"
    windows = encoder.split_windows(text)
    full = Tokenizer.from_str(encoder.tokenizer.to_str())
    full.no_truncation()
    full.no_padding()
    expected_offsets = {
        offset
        for offset, special in zip(full.encode(text).offsets, full.encode(text).special_tokens_mask)
        if not special
    }
    covered = set()
    for window in windows:
        assert len(window.ids) <= 128
        assert window.ids[0] == 3 and window.ids[-1] == 4
        covered.update(
            offset
            for offset, special in zip(window.offsets, window.special_tokens_mask)
            if not special
        )
    assert covered == expected_offsets
    assert len(windows) == 3
    assert windows[0].offsets[-33:-1] == windows[1].offsets[1:33]
    assert 5 in windows[-1].ids


def test_tail_changes_aggregated_embedding_but_short_inputs_remain_identical() -> None:
    base, _ = encoder_fixture(MultilingualOnnxEmbedding)
    windowed, feeds = encoder_fixture(WindowedMultilingualOnnxEmbedding)
    short = "head tail"
    np.testing.assert_array_equal(base([short]), windowed([short]))
    text = "head " * 200 + "tail"
    truncated = np.asarray(base([text]))
    full = np.asarray(windowed([text]))
    assert truncated[0, 1] == 0.0
    assert full[0, 1] > 0.0
    np.testing.assert_allclose(np.linalg.norm(full, axis=1), [1.0], atol=1e-6)
    assert all(feed["input_ids"].shape[1] <= 128 for feed in feeds)
    assert windowed([]) == []


def test_multiple_texts_keep_order_and_one_vector_per_original_input() -> None:
    encoder, _ = encoder_fixture(WindowedMultilingualOnnxEmbedding)
    texts = ["head", "head " * 180 + "tail", "tail"]
    together = encoder(texts)
    separate = [encoder([text])[0] for text in texts]
    np.testing.assert_allclose(together, separate, atol=1e-6)
    assert np.asarray(together).shape == (3, 2)


@pytest.mark.parametrize("payload_count", [0, 126, 127, 281])
def test_window_audit_proves_payload_conservation_at_boundaries(payload_count: int) -> None:
    encoder, _ = encoder_fixture(WindowedMultilingualOnnxEmbedding)
    text = "head " * payload_count
    audit = encoder.window_statistics([text])[0]
    assert audit["complete"] is True
    assert audit["payload_token_count"] == payload_count
    assert audit["covered_payload_token_count"] == payload_count
    assert audit["window_count"] == (
        1 if payload_count <= 126 else 2 if payload_count == 127 else 3
    )
