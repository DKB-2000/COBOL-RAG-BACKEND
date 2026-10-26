import re
from hashlib import sha256

from legacy_rag.ingestion.models import SourceChunk, SourceDocument

_DIVISION_PATTERN = re.compile(
    r"^\s{7}([A-Z][A-Z0-9-]*(?:\s+[A-Z][A-Z0-9-]*)*)\s+DIVISION(?:\.|\s|$)",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    r"^\s{7}([A-Z][A-Z0-9-]*(?:\s+[A-Z][A-Z0-9-]*)*)\s+SECTION\.\s*$",
    re.IGNORECASE,
)
_PARAGRAPH_PATTERN = re.compile(
    r"^\s{7}([A-Z][A-Z0-9-]*)\.\s*$",
    re.IGNORECASE,
)


def chunk_document(document: SourceDocument) -> list[SourceChunk]:
  chunk_index = 0

  identity = (
      f"file-v1\0{document.source_path}\0"
      f"{document.content_hash}\0{chunk_index}"
  )
  chunk_id = sha256(identity.encode("utf-8")).hexdigest()

  return [
      SourceChunk(
          chunk_id=chunk_id,
          text=document.text,
          source_path=document.source_path,
          language=document.language,
          symbol=document.symbol,
          content_hash=document.content_hash,
          chunk_index=chunk_index,
      )
  ]


def chunk_cobol_structure(document: SourceDocument) -> list[SourceChunk]:
    boundaries: list[tuple[int, str]] = []
    offset = 0
    in_procedure_division = False

    for line in document.text.splitlines(keepends=True):
        division_match = _DIVISION_PATTERN.match(line)
        section_match = _SECTION_PATTERN.match(line)
        paragraph_match = _PARAGRAPH_PATTERN.match(line)

        if division_match is not None:
            division_name = division_match.group(1).upper()
            boundaries.append((offset, f"{division_name} DIVISION"))
            in_procedure_division = division_name == "PROCEDURE"
        elif section_match is not None:
            section_name = section_match.group(1).upper()
            boundaries.append((offset, f"{section_name} SECTION"))
        elif in_procedure_division and paragraph_match is not None:
            boundaries.append((offset, paragraph_match.group(1).upper()))

        offset += len(line)

    if not boundaries:
        boundaries.append((0, document.symbol))
    elif boundaries[0][0] > 0:
        boundaries[0] = (0, boundaries[0][1])

    chunks: list[SourceChunk] = []
    for chunk_index, (start, symbol) in enumerate(boundaries):
        end = boundaries[chunk_index + 1][0] if chunk_index + 1 < len(boundaries) else None
        text = document.text[start:end]
        identity = (
            f"cobol-structure-v1\0{document.source_path}\0"
            f"{document.content_hash}\0{chunk_index}\0{symbol}"
        )
        chunks.append(
            SourceChunk(
                chunk_id=sha256(identity.encode("utf-8")).hexdigest(),
                text=text,
                source_path=document.source_path,
                language=document.language,
                symbol=symbol,
                content_hash=document.content_hash,
                chunk_index=chunk_index,
            )
        )

    return chunks
