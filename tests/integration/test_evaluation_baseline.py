import json
from pathlib import Path

import chromadb

from legacy_rag.evaluation.baseline import (
  run_file_level_baseline,
)


def test_run_file_level_baseline_connects_full_pipeline(
  tmp_path: Path,
) -> None:
  data_root = tmp_path / "data"
  samples_root = data_root / "samples"
  samples_root.mkdir(parents=True)

  source_path = samples_root / "hello.cbl"
  source_path.write_text(
      (
          "       IDENTIFICATION DIVISION.\n"
          "       PROGRAM-ID. HELLO.\n"
      ),
      encoding="utf-8",
  )

  dataset_path = data_root / "questions.jsonl"
  dataset_path.write_text(
      json.dumps(
          {
              "id": "q001",
              "question": "HELLO 프로그램은 무엇인가?",
              "expected_sources": [
                  "samples/hello.cbl",
              ],
              "expected_symbols": ["HELLO"],
              "answerable": True,
              "tags": ["cobol"],
          },
          ensure_ascii=False,
      )
      + "\n",
      encoding="utf-8",
  )

  client = chromadb.PersistentClient(
      path=str(tmp_path / "chroma"),
  )
  collection = client.create_collection(
      name="test-chunks",
      embedding_function=None,
      configuration={"hnsw": {"space": "cosine"}},
  )

  def embed_texts(
      texts: list[str],
  ) -> list[list[float]]:
      return [
          [1.0, 0.0, 0.0]
          for _ in texts
      ]

  summary = run_file_level_baseline(
      data_root=data_root,
      dataset_path=dataset_path,
      collection=collection,
      embed_texts=embed_texts,
      k=5,
  )

  assert collection.count() == 1
  assert summary.evaluated_cases == 1
  assert summary.hit_at_k == 1.0
  assert summary.mrr == 1.0