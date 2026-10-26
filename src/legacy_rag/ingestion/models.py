from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceDocument:
  text: str
  source_path: str
  language: str
  symbol: str
  content_hash: str


@dataclass(frozen=True, slots=True)
class SourceChunk:
  chunk_id: str
  text: str
  source_path: str
  language: str
  symbol: str
  content_hash: str
  chunk_index: int