import re
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

from legacy_rag.ingestion.models import SourceDocument

_PROGRAM_ID_PATTERN = re.compile(
    r"\bPROGRAM-ID\.\s+([A-Z0-9-]+)",
    re.IGNORECASE,
)


def load_cobol_file(
    path: Path,
    *,
    data_root: Path,
) -> SourceDocument:
    resolved_path = path.resolve()
    resolved_root = data_root.resolve()

    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"source path is outside data root: {path}") from exc

    if resolved_path.suffix.lower() != ".cbl":
        raise ValueError(f"unsupported file extension: {resolved_path.suffix}")

    text = resolved_path.read_text(encoding="utf-8")

    if not text:
        raise ValueError(f"empty source file: {path}")

    program_id_match = _PROGRAM_ID_PATTERN.search(text)
    if program_id_match is None:
        raise ValueError(f"PROGRAM-ID not found: {path}")

    symbol = program_id_match.group(1).upper()
    content_hash = sha256(text.encode("utf-8")).hexdigest()

    return SourceDocument(
        text=text,
        source_path=relative_path.as_posix(),
        language="cobol",
        symbol=symbol,
        content_hash=content_hash,
    )


def load_cobol_files(
    paths: Iterable[Path],
    *,
    data_root: Path,
) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    seen_paths: set[Path] = set()

    for path in paths:
        resolved_path = path.resolve()

        if resolved_path in seen_paths:
            continue

        seen_paths.add(resolved_path)
        documents.append(load_cobol_file(path, data_root=data_root))

    return documents
