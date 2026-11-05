"""Zip containers are measured before anything inflates them, and archives are refused."""

from __future__ import annotations

import asyncio
import io
import tarfile
import zipfile

import pytest

from engine.archive_guard import UnsafeArchive, check_tar, check_zip, unsafe_name
from engine.knowledge.extractors.dispatch import extract_document
from engine.sources.normalize import NormalizeError, xlsx_rows


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_real_ratio_of_a_zip_bomb_is_refused_without_inflating(monkeypatch):
    bomb = _zip({"word/document.xml": b"0" * (64 * 1024 * 1024)})
    assert len(bomb) < 200_000
    with pytest.raises(UnsafeArchive, match="zip bomb"):
        check_zip(io.BytesIO(bomb))


def test_total_size_and_entry_limits(monkeypatch):
    monkeypatch.setenv("ARCHIVE_MAX_TOTAL_BYTES", "100")
    with pytest.raises(UnsafeArchive, match="expand past"):
        check_zip(io.BytesIO(_zip({"a": b"x" * 200})))
    monkeypatch.setenv("ARCHIVE_MAX_TOTAL_BYTES", "100000")
    monkeypatch.setenv("ARCHIVE_MAX_ENTRIES", "2")
    with pytest.raises(UnsafeArchive, match="holds 3 files"):
        check_zip(io.BytesIO(_zip({"a": b"", "b": b"", "c": b""})))


@pytest.mark.parametrize(
    "name", ["../evil", "a/../../evil", "/etc/passwd", "..\\evil", "C:\\windows\\x"]
)
def test_traversal_names_are_refused(name):
    assert unsafe_name(name)
    with pytest.raises(UnsafeArchive, match="leaves its folder"):
        check_zip(io.BytesIO(_zip({name: b"x"})))


def test_ordinary_names_pass():
    assert not unsafe_name("word/document.xml")
    assert not unsafe_name("a..b/c.txt")
    check_zip(io.BytesIO(_zip({"word/document.xml": b"<x/>" * 100})))


def test_a_file_that_is_not_a_zip_is_left_to_its_parser():
    check_zip(io.BytesIO(b"plain text"))


def test_docx_bomb_stops_the_extractor_before_python_docx(tmp_path, monkeypatch):
    path = tmp_path / "bomb.docx"
    path.write_bytes(_zip({"word/document.xml": b"0" * (64 * 1024 * 1024)}))
    with pytest.raises(UnsafeArchive):
        asyncio.run(extract_document(str(path), file_type="docx"))


@pytest.mark.parametrize("kind", ["zip", "tar", "gz", "7z"])
def test_archives_are_not_read_as_text(tmp_path, kind):
    path = tmp_path / f"x.{kind}"
    path.write_bytes(b"not text")
    with pytest.raises(UnsafeArchive, match="not ingested"):
        asyncio.run(extract_document(str(path), file_type=kind))


def test_workbook_bomb_from_a_watched_source_is_refused():
    body = _zip({"xl/workbook.xml": b"0" * (64 * 1024 * 1024)})
    with pytest.raises(NormalizeError, match="zip bomb"):
        xlsx_rows(body)


def _tar(add) -> tarfile.TarFile:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        add(t)
    buf.seek(0)
    return tarfile.open(fileobj=buf)


def test_tar_with_a_link_or_traversal_is_refused():
    def link(t):
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)

    with pytest.raises(UnsafeArchive, match="link"):
        check_tar(_tar(link))

    def climb(t):
        info = tarfile.TarInfo("../../evil")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(UnsafeArchive, match="leaves its folder"):
        check_tar(_tar(climb))
