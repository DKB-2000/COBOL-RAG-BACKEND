from functools import cached_property

import numpy as np
from tokenizers import Encoding, Tokenizer

# Keep existing evaluation imports and test injection paths compatible.
from legacy_rag.retrieval.embedding import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_REVISION,
    MultilingualOnnxEmbedding,
    masked_mean_pool,
    ort,
)

__all__ = [
    "MODEL_FILES", "MODEL_ID", "MODEL_REVISION", "MultilingualOnnxEmbedding",
    "WindowedMultilingualOnnxEmbedding", "masked_mean_pool", "ort",
]


class WindowedMultilingualOnnxEmbedding(MultilingualOnnxEmbedding):
    overlap = 32

    @cached_property
    def window_tokenizer(self) -> Tokenizer:
        tokenizer = Tokenizer.from_str(self.tokenizer.to_str())
        tokenizer.no_padding()
        tokenizer.no_truncation()
        return tokenizer

    def split_windows(self, text: str) -> tuple[Encoding, ...]:
        tokenizer = self.window_tokenizer
        payload = tokenizer.encode(text, add_special_tokens=False)
        payload.truncate(
            self.max_length - tokenizer.num_special_tokens_to_add(False),
            stride=self.overlap,
        )
        first = tokenizer.post_process(payload, add_special_tokens=True)
        return (first, *first.overflowing)

    def window_statistics(self, texts: list[str]) -> list[dict]:
        full = Tokenizer.from_str(self.tokenizer.to_str())
        full.no_truncation()
        full.no_padding()
        statistics = []
        for text in texts:
            windows = self.split_windows(text)
            original = full.encode(text)
            expected = [
                token
                for token, special in zip(original.ids, original.special_tokens_mask, strict=True)
                if not special
            ]
            covered = []
            ranges = []
            for index, window in enumerate(windows):
                payload = [
                    token
                    for token, special in zip(window.ids, window.special_tokens_mask, strict=True)
                    if not special
                ]
                covered.extend(payload if index == 0 else payload[self.overlap :])
                offsets = [
                    offset
                    for offset, special in zip(
                        window.offsets, window.special_tokens_mask, strict=True
                    )
                    if not special
                ]
                ranges.append(
                    [
                        min((start for start, _ in offsets), default=0),
                        max((end for _, end in offsets), default=0),
                    ]
                )
            statistics.append(
                {
                    "window_count": len(windows),
                    "payload_token_count": len(expected),
                    "covered_payload_token_count": len(covered),
                    "complete": covered == expected,
                    "character_ranges": ranges,
                }
            )
        return statistics

    def __call__(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        groups = [self.split_windows(text) for text in texts]
        windows = [window for group in groups for window in group]
        vectors = np.concatenate(
            [self._embed_batch(windows[start : start + 16]) for start in range(0, len(windows), 16)]
        )
        result = []
        offset = 0
        for group in groups:
            if len(group) == 1:
                pooled = vectors[offset]
            else:
                pooled = vectors[offset : offset + len(group)].mean(axis=0)
                pooled = pooled / max(float(np.linalg.norm(pooled)), 1e-12)
            result.append(pooled.tolist())
            offset += len(group)
        return result
