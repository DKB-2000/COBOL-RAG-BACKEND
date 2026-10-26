from hashlib import sha256
from pathlib import Path

import pytest

from legacy_rag.ingestion.loader import (
    load_cobol_file,
    load_cobol_files,
)


def test_load_cobol_file_returns_text_and_relative_source_path(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    source_path = data_root / "samples" / "hello.cbl"
    source_path.parent.mkdir(parents=True)
    cobol_text = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HELLO.\n"
    source_path.write_text(cobol_text, encoding="utf-8")

    document = load_cobol_file(source_path, data_root=data_root)

    assert document.text == cobol_text
    assert document.source_path == "samples/hello.cbl"
    assert document.language == "cobol"

    expected_hash = sha256(cobol_text.encode("utf-8")).hexdigest()
    assert document.content_hash == expected_hash

    assert document.symbol == "HELLO"


def test_load_cobol_file_rejects_unsupported_extension(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    source_path = data_root / "samples" / "hello.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("not cobol", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported file extension"):
        load_cobol_file(source_path, data_root=data_root)


def test_load_cobol_file_rejects_empty_file(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    source_path = data_root / "samples" / "empty.cbl"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty source file"):
        load_cobol_file(source_path, data_root=data_root)


def test_load_cobol_file_rejects_path_outside_data_root(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()

    source_path = tmp_path / "outside.cbl"
    source_path.write_text("       PROGRAM-ID. OUTSIDE.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside data root"):
        load_cobol_file(source_path, data_root=data_root)


def test_load_cobol_file_supports_uppercase_extension_and_utf8(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    source_path = data_root / "samples" / "ORDERMAIN.CBL"
    source_path.parent.mkdir(parents=True)

    source_path.write_bytes(
        (
            "000010 IDENTIFICATION DIVISION.\r\n"
            "000020 PROGRAM-ID. ORDERMAIN.\r\n"
            "000030* 注文テスト\r\n"
        ).encode()
    )

    document = load_cobol_file(source_path, data_root=data_root)

    assert document.symbol == "ORDERMAIN"
    assert "注文テスト" in document.text
    assert "\r" not in document.text
    assert document.text.endswith("\n")


def test_load_cobol_file_rejects_missing_file(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    source_path = data_root / "samples" / "missing.cbl"

    with pytest.raises(FileNotFoundError):
        load_cobol_file(source_path, data_root=data_root)


def test_load_cobol_file_rejects_missing_program_id(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    source_path = data_root / "samples" / "missing-program-id.cbl"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "       IDENTIFICATION DIVISION.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="PROGRAM-ID not found"):
        load_cobol_file(source_path, data_root=data_root)


def test_load_cobol_files_removes_duplicates_and_preserves_order(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    samples_root = data_root / "samples"
    samples_root.mkdir(parents=True)

    first_path = samples_root / "first.cbl"
    first_path.write_text(
        "       PROGRAM-ID. FIRST.\n",
        encoding="utf-8",
    )

    second_path = samples_root / "second.cbl"
    second_path.write_text(
        "       PROGRAM-ID. SECOND.\n",
        encoding="utf-8",
    )

    documents = load_cobol_files(
        [first_path, first_path, second_path],
        data_root=data_root,
    )

    assert [document.source_path for document in documents] == [
        "samples/first.cbl",
        "samples/second.cbl",
    ]
def test_baseline_and_authorized_sample_scopes_are_separate() -> None:
  project_root = Path(__file__).resolve().parents[2]
  data_root = project_root / "data"
  samples_root = data_root / "samples"
  authorized_root = samples_root / "authorized-test"

  baseline_paths = sorted(
      path
      for path in samples_root.iterdir()
      if path.is_file() and path.suffix.lower() == ".cbl"
  )
  authorized_paths = sorted(
      path
      for path in authorized_root.iterdir()
      if path.is_file() and path.suffix.lower() == ".cbl"
  )

  baseline_documents = load_cobol_files(
      baseline_paths,
      data_root=data_root,
  )
  authorized_documents = load_cobol_files(
      authorized_paths,
      data_root=data_root,
  )

  assert len(baseline_documents) == 5
  assert len(authorized_documents) == 5

  assert all(
      document.source_path.startswith("samples/")
      and not document.source_path.startswith("samples/authorized-test/")
      for document in baseline_documents
  )
  assert all(
      document.source_path.startswith("samples/authorized-test/")
      for document in authorized_documents
  )
