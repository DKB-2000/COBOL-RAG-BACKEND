import re
from dataclasses import dataclass

from legacy_rag.ingestion.models import SourceChunk

_TOKENS = re.compile(
    r'"(?:[^"\n]|"")*"|\'(?:[^\'\n]|\'\')*\'|\*>[^\n]*|[A-Z][A-Z0-9-]*|\d+|\.',
    re.IGNORECASE,
)
_DECLARATION = re.compile(
    r"^\s*(?:0[1-9]|[1-4][0-9]|66|77|88|FD|SD)\s+([A-Z][A-Z0-9-]*)\b",
    re.IGNORECASE,
)
_PRIORITY = {
    "using-contract": 0,
    "perform": 1,
    "perform-caller": 1,
    "call": 2,
    "call-caller": 2,
    "declaration": 3,
}


@dataclass(frozen=True, slots=True)
class ChunkRelation:
    target_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class ContextAddition:
    seed_id: str
    target_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class ExpandedContext:
    chunks: tuple[SourceChunk, ...]
    additions: tuple[ContextAddition, ...]
    skipped_ids: tuple[str, ...]


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if len(line) < 7 or line[6] not in "*/"]


def build_cobol_relations(chunks: list[SourceChunk]) -> dict[str, tuple[ChunkRelation, ...]]:
    """Limited lexical relations for fixed-format samples, not a COBOL parser."""
    by_id = {c.chunk_id: c for c in chunks}
    symbols = {(c.source_path, c.symbol.upper()): c for c in chunks}
    tokens = {
        c.chunk_id: [
            token.upper()
            for token in _TOKENS.findall("\n".join(_code_lines(c.text)))
            if not token.startswith("*>")
        ]
        for c in chunks
    }
    declarations: dict[tuple[str, str], list[SourceChunk]] = {}
    programs: dict[str, set[str]] = {}
    edges: dict[str, set[ChunkRelation]] = {c.chunk_id: set() for c in chunks}

    def add(source: SourceChunk, target: SourceChunk, kind: str) -> None:
        if source.chunk_id != target.chunk_id:
            edges[source.chunk_id].add(ChunkRelation(target.chunk_id, kind))

    for c in chunks:
        words = tokens[c.chunk_id]
        for i in range(len(words) - 2):
            if words[i : i + 2] == ["PROGRAM-ID", "."]:
                programs.setdefault(words[i + 2], set()).add(c.source_path)
        if c.symbol.upper().endswith(" SECTION"):
            for line in _code_lines(c.text):
                match = _DECLARATION.match(line)
                if match:
                    declarations.setdefault((c.source_path, match[1].upper()), []).append(c)

    for c in chunks:
        words = tokens[c.chunk_id]
        for i, word in enumerate(words[:-1]):
            target_word = words[i + 1]
            if word == "PERFORM" and words[i + 2 : i + 3] not in (["THRU"], ["THROUGH"]):
                target = symbols.get((c.source_path, target_word))
                if target:
                    add(c, target, "perform")
                    add(target, c, "perform-caller")
            elif word == "CALL" and target_word.startswith(('"', "'")):
                sources = programs.get(target_word[1:-1], set())
                if len(sources) == 1:
                    target_source = next(iter(sources))
                    for symbol in (
                        "IDENTIFICATION DIVISION",
                        "PROCEDURE DIVISION",
                        "LINKAGE SECTION",
                    ):
                        target = symbols.get((target_source, symbol))
                        if target:
                            add(c, target, "call")
                            add(target, c, "call-caller")
        if c.symbol.upper() == "PROCEDURE DIVISION" and "USING" in words:
            linkage = symbols.get((c.source_path, "LINKAGE SECTION"))
            if linkage:
                add(c, linkage, "using-contract")
                add(linkage, c, "using-contract")
        for word in set(words):
            for target in declarations.get((c.source_path, word), []):
                add(c, target, "declaration")

    return {
        key: tuple(
            sorted(
                value,
                key=lambda r: (
                    _PRIORITY[r.kind],
                    by_id[r.target_id].source_path,
                    by_id[r.target_id].chunk_index,
                    r.kind,
                ),
            )
        )
        for key, value in edges.items()
    }


def expand_related_chunks(
    seeds: list[SourceChunk],
    chunks: list[SourceChunk],
    relations: dict[str, tuple[ChunkRelation, ...]],
    *,
    max_chunks: int = 10,
    max_characters: int = 4000,
) -> ExpandedContext:
    if max_chunks < 1 or max_characters < 1:
        raise ValueError("context budgets must be positive")
    by_id = {c.chunk_id: c for c in chunks}
    selected: list[SourceChunk] = []
    seen: set[str] = set()
    skipped: list[str] = []
    characters = 0

    def take(chunk: SourceChunk) -> bool:
        nonlocal characters
        if chunk.chunk_id in seen:
            return False
        seen.add(chunk.chunk_id)
        if len(selected) >= max_chunks or characters + len(chunk.text) > max_characters:
            skipped.append(chunk.chunk_id)
            return False
        selected.append(chunk)
        characters += len(chunk.text)
        return True

    for seed in seeds:
        take(by_id[seed.chunk_id])
    retained_seeds = tuple(selected)
    candidates = sorted(
        (
            (
                _PRIORITY[r.kind],
                rank,
                by_id[r.target_id].source_path,
                by_id[r.target_id].chunk_index,
                r.kind,
                seed.chunk_id,
                r.target_id,
            )
            for rank, seed in enumerate(retained_seeds)
            for r in relations.get(seed.chunk_id, ())
        ),
    )
    additions = []
    for _, _, _, _, kind, seed_id, target_id in candidates:
        if take(by_id[target_id]):
            additions.append(ContextAddition(seed_id, target_id, kind))
    return ExpandedContext(tuple(selected), tuple(additions), tuple(skipped))
