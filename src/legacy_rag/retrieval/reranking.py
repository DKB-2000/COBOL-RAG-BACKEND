"""Local INT8 reranking; source text and vector scores remain unchanged."""
import math
from pathlib import Path
from threading import Lock
from typing import Protocol

from legacy_rag.retrieval.chroma_store import SearchResult
from legacy_rag.retrieval.context import assemble_context
from legacy_rag.retrieval.embedding_input import build_contextual_embedding_text

RERANKER_ID = "BAAI/bge-reranker-v2-m3"
RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
CANDIDATE_COUNT = 30


class Searcher(Protocol):
    def search(self, *, query: str, limit: int) -> list[SearchResult]: ...


class Ranker(Protocol):
    def rank(self, query: str, candidates: list[SearchResult]) -> list[SearchResult]: ...


class LocalBgeReranker:
    """Load once on first nonempty request, serialize CPU inference, never download."""

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._lock = Lock()
        self._model = None
        self._tokenizer = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if not self._model_dir.is_dir():
            raise RuntimeError("Local reranker model is not installed")
        torch.set_num_threads(4)
        tokenizer = AutoTokenizer.from_pretrained(
            self._model_dir, local_files_only=True, trust_remote_code=False,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self._model_dir, local_files_only=True, trust_remote_code=False,
        ).to("cpu").eval()
        model = torch.ao.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True,
        )
        if not any(isinstance(m, torch.ao.nn.quantized.dynamic.Linear) for m in model.modules()):
            raise RuntimeError("Reranker quantization failed")
        self._tokenizer, self._model = tokenizer, model

    def rank(self, query: str, candidates: list[SearchResult]) -> list[SearchResult]:
        if not candidates:
            return []
        with self._lock:
            self._load()
            import torch

            pairs = [(query, build_contextual_embedding_text(row)) for row in candidates]
            lengths = self._tokenizer(pairs, truncation=False, padding=False)["input_ids"]
            indices = sorted(range(len(pairs)), key=lambda i: len(lengths[i]))
            scores = [0.0] * len(pairs)
            for offset in range(0, len(indices), 4):
                group = indices[offset:offset + 4]
                inputs = self._tokenizer(
                    [pairs[i] for i in group], padding=True, truncation=True,
                    max_length=512, return_tensors="pt",
                )
                with torch.inference_mode():
                    values = self._model(**inputs, return_dict=True).logits.view(-1).float().tolist()
                if len(values) != len(group) or not all(math.isfinite(v) for v in values):
                    raise RuntimeError("Invalid reranker scores")
                for index, value in zip(group, values, strict=True):
                    scores[index] = value
            return [candidates[i] for i in sorted(indices, key=lambda i: (-scores[i], i))]


class RerankedSearcher:
    def __init__(self, searcher: Searcher, ranker: Ranker) -> None:
        self._searcher, self._ranker = searcher, ranker

    def search(self, *, query: str, limit: int) -> list[SearchResult]:
        candidates = self._searcher.search(query=query, limit=max(CANDIDATE_COUNT, limit))
        if not candidates:
            return []
        return self._ranker.rank(query, candidates)[:limit]


class ContextSearcher:
    """Assemble from all ranked candidates, after any public-corpus filtering."""

    def __init__(self, searcher: Searcher) -> None:
        self._searcher = searcher

    def search(self, *, query: str, limit: int) -> list[SearchResult]:
        candidates = self._searcher.search(query=query, limit=CANDIDATE_COUNT)
        return list(assemble_context(candidates, max_chunks=limit))
