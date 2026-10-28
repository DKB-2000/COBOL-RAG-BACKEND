import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Encoding, Tokenizer

from legacy_rag.retrieval.embedding_input import normalize_code_embedding_text

MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
MODEL_FILES = (
    "onnx/model.onnx", "tokenizer.json", "sentence_bert_config.json", "1_Pooling/config.json",
)


def masked_mean_pool(tokens: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[..., None].astype(np.float32)
    pooled = (tokens * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
    return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)


class MultilingualOnnxEmbedding:
    """Local CPU encoder shared by the API and fixed-baseline evaluation."""

    def __init__(self, model_dir: Path) -> None:
        config = json.loads((model_dir / "sentence_bert_config.json").read_text(encoding="utf-8"))
        pooling = json.loads((model_dir / "1_Pooling/config.json").read_text(encoding="utf-8"))
        if (
            config["max_seq_length"] != 128
            or not pooling["pooling_mode_mean_tokens"]
            or any(
                pooling[name]
                for name in (
                    "pooling_mode_cls_token",
                    "pooling_mode_max_tokens",
                    "pooling_mode_mean_sqrt_len_tokens",
                )
            )
        ):
            raise ValueError("unexpected multilingual model configuration")
        self.max_length = config["max_seq_length"]
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=self.max_length)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_dir / "onnx/model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def token_lengths(self, texts: list[str]) -> list[int]:
        tokenizer = Tokenizer.from_str(self.tokenizer.to_str())
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return [len(item.ids) for item in tokenizer.encode_batch(texts)]

    def __call__(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for start in range(0, len(texts), 16):
            encoded = self.tokenizer.encode_batch(texts[start : start + 16])
            embeddings.extend(self._embed_batch(encoded).tolist())
        return embeddings

    def _embed_batch(self, encoded: list[Encoding]) -> np.ndarray:
        shape = (len(encoded), max(len(item.ids) for item in encoded))
        inputs = {
            "input_ids": np.full(shape, 1, dtype=np.int64),
            "attention_mask": np.zeros(shape, dtype=np.int64),
            "token_type_ids": np.zeros(shape, dtype=np.int64),
        }
        for row, item in enumerate(encoded):
            length = len(item.ids)
            inputs["input_ids"][row, :length] = item.ids
            inputs["attention_mask"][row, :length] = item.attention_mask
            inputs["token_type_ids"][row, :length] = item.type_ids
        feed = {item.name: inputs[item.name] for item in self.session.get_inputs()}
        tokens = self.session.run(["last_hidden_state"], feed)[0]
        return masked_mean_pool(tokens, inputs["attention_mask"])


class IdentifierAwareOnnxEmbedding(MultilingualOnnxEmbedding):
    """Keep original meaning and add normalized identifier words at equal weight."""

    def __call__(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        original = super().__call__(texts)
        normalized_texts = [normalize_code_embedding_text(text) for text in texts]
        if normalized_texts == texts:
            return original
        normalized = super().__call__(normalized_texts)
        pooled = (np.asarray(original) + np.asarray(normalized)) / 2
        pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        return pooled.tolist()
