from legacy_rag.ingestion.models import SourceChunk
from legacy_rag.retrieval.context_expansion import build_cobol_relations, expand_related_chunks


def chunk(identity: str, text: str, *, source: str = "a.cbl", symbol: str = "MAIN", index: int = 0):
    return SourceChunk(identity, text, source, "cobol", symbol, "hash", index)


def test_perform_is_local_bidirectional_and_excludes_comments_strings_and_prefixes() -> None:
    chunks = [
        chunk(
            "main",
            "       MAIN.\n           PERFORM TARGET\n"
            '           DISPLAY "PERFORM FAKE"\n'
            "      *    PERFORM FAKE\n"
            "           CONTINUE *> PERFORM FAKE\n           PERFORM TARGET-OTHER",
        ),
        chunk("target", "       TARGET.\n           CONTINUE.", symbol="TARGET", index=1),
        chunk("fake", "       FAKE.\n           CONTINUE.", symbol="FAKE", index=2),
        chunk(
            "other-file", "       TARGET.\n           CONTINUE.", source="b.cbl", symbol="TARGET"
        ),
    ]
    relations = build_cobol_relations(chunks)
    assert [(r.target_id, r.kind) for r in relations["main"]] == [("target", "perform")]
    assert [(r.target_id, r.kind) for r in relations["target"]] == [("main", "perform-caller")]


def test_static_call_links_contracts_and_callers_without_dynamic_call_guessing() -> None:
    chunks = [
        chunk(
            "caller",
            '       MAIN.\n           CALL "SUB" USING WS-ARG.\n'
            "           CALL WS-DYNAMIC.\n           DISPLAY 'CALL \"BAD\"'.",
        ),
        chunk(
            "id",
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUB.",
            source="sub.cbl",
            symbol="IDENTIFICATION DIVISION",
        ),
        chunk(
            "using",
            "       PROCEDURE DIVISION USING LK-ARG.",
            source="sub.cbl",
            symbol="PROCEDURE DIVISION",
            index=2,
        ),
        chunk(
            "linkage",
            "       LINKAGE SECTION.\n       01 LK-ARG PIC X.",
            source="sub.cbl",
            symbol="LINKAGE SECTION",
            index=1,
        ),
    ]
    relations = build_cobol_relations(chunks)
    assert {r.target_id for r in relations["caller"] if r.kind == "call"} == {
        "id",
        "using",
        "linkage",
    }
    assert any(r.target_id == "caller" and r.kind == "call-caller" for r in relations["id"])
    assert any(r.target_id == "using" and r.kind == "using-contract" for r in relations["linkage"])


def test_declaration_references_are_exact_local_and_do_not_expand_back_to_all_users() -> None:
    chunks = [
        chunk("main", "       MAIN.\n           MOVE WS-X TO WS-Y.\n"),
        chunk(
            "decl",
            "       WORKING-STORAGE SECTION.\n       01 WS-X PIC X.",
            symbol="WORKING-STORAGE SECTION",
            index=1,
        ),
        chunk(
            "prefix",
            "       WORKING-STORAGE SECTION.\n       01 WS-X-OTHER PIC X.",
            source="b.cbl",
            symbol="WORKING-STORAGE SECTION",
        ),
    ]
    relations = build_cobol_relations(chunks)
    assert [(r.target_id, r.kind) for r in relations["main"]] == [("decl", "declaration")]
    assert relations["decl"] == ()


def test_expansion_preserves_seeds_deduplicates_and_stops_after_one_hop() -> None:
    chunks = [
        chunk("a", "       A.\n           PERFORM B.", symbol="A"),
        chunk("b", "       B.\n           PERFORM C.", symbol="B", index=1),
        chunk("c", "       C.\n           CONTINUE.", symbol="C", index=2),
    ]
    relations = build_cobol_relations(chunks)
    selected = expand_related_chunks([chunks[0], chunks[0]], chunks, relations)
    assert [c.chunk_id for c in selected.chunks] == ["a", "b"]
    assert len(selected.additions) == 1
    assert selected.additions[0].seed_id == "a"
    assert chunks[2].chunk_id not in [c.chunk_id for c in selected.chunks]


def test_whole_chunk_budgets_skip_oversized_candidates_and_retain_later_ones() -> None:
    chunks = [
        chunk("a", "       A.\n           PERFORM B\n           PERFORM C.", symbol="A"),
        chunk("b", "       B.\n" + " " * 200, symbol="B", index=1),
        chunk("c", "       C.\n", symbol="C", index=2),
    ]
    relations = build_cobol_relations(chunks)
    selected = expand_related_chunks([chunks[0]], chunks, relations, max_characters=100)
    assert [c.chunk_id for c in selected.chunks] == ["a", "c"]
    assert "b" in selected.skipped_ids
    assert sum(len(c.text) for c in selected.chunks) <= 100
    selected = expand_related_chunks([chunks[0]], chunks, relations, max_chunks=1)
    assert [c.chunk_id for c in selected.chunks] == ["a"]


def test_using_and_perform_priority_is_stable_when_corpus_order_changes() -> None:
    chunks = [
        chunk(
            "main",
            "       MAIN.\n           PERFORM TARGET\n           MOVE WS-X TO WS-X.",
            symbol="MAIN",
        ),
        chunk("target", "       TARGET.\n           CONTINUE.", symbol="TARGET", index=2),
        chunk(
            "decl",
            "       WORKING-STORAGE SECTION.\n       01 WS-X PIC X.",
            symbol="WORKING-STORAGE SECTION",
            index=1,
        ),
    ]
    selected = expand_related_chunks(
        [chunks[0]], chunks, build_cobol_relations(chunks), max_chunks=2
    )
    shuffled = list(reversed(chunks))
    repeat = expand_related_chunks(
        [chunks[0]], shuffled, build_cobol_relations(shuffled), max_chunks=2
    )
    assert selected == repeat
    assert [c.chunk_id for c in selected.chunks] == ["main", "target"]


def test_unsupported_ranges_and_ambiguous_program_names_are_not_guessed() -> None:
    chunks = [
        chunk("main", '       MAIN.\n           PERFORM TARGET THRU LAST.\n           CALL "SUB".'),
        chunk("target", "       TARGET.\n           CONTINUE.", symbol="TARGET", index=1),
        chunk(
            "sub1",
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUB.",
            source="sub1.cbl",
            symbol="IDENTIFICATION DIVISION",
        ),
        chunk(
            "sub2",
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUB.",
            source="sub2.cbl",
            symbol="IDENTIFICATION DIVISION",
        ),
    ]
    assert build_cobol_relations(chunks)["main"] == ()
