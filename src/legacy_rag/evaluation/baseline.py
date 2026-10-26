from collections.abc import Callable
from pathlib import Path

from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embeddings

from legacy_rag.evaluation.dataset import load_evaluation_cases
from legacy_rag.evaluation.runner import RetrievalReport, evaluate_retrieval
from legacy_rag.ingestion.chunker import chunk_document
from legacy_rag.ingestion.loader import load_cobol_files
from legacy_rag.retrieval.chroma_store import ChromaChunkStore


def run_file_level_baseline(
  *,
  data_root: Path,
  dataset_path: Path,
    collection: Collection,
    embed_texts: Callable[[list[str]], Embeddings],
    k: int,
) -> RetrievalReport:
  samples_root = data_root / "samples"
  source_paths = sorted(
      path
      for path in samples_root.iterdir()
      if path.is_file()
      and path.suffix.lower() == ".cbl"
  )

  documents = load_cobol_files(
      source_paths,
      data_root=data_root,
  )
  chunks = [
      chunk
      for document in documents
      for chunk in chunk_document(document)
  ]

  chunk_embeddings = embed_texts(
      [chunk.text for chunk in chunks]
  )

  store = ChromaChunkStore(collection)
  store.rebuild(
      chunks,
      embeddings=chunk_embeddings,
  )

  cases = load_evaluation_cases(dataset_path)

  def retrieve_sources(
      question: str,
      limit: int,
  ) -> list[str]:
      query_embeddings = embed_texts([question])
      query_embedding = [
          float(value)
          for value in query_embeddings[0]
      ]

      results = store.search(
          query_embedding=query_embedding,
          limit=limit,
      )

      return [
          result.source_path
          for result in results
      ]

  return evaluate_retrieval(
      cases,
      retrieve_sources,
      k=k,
  )
