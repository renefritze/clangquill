"""Unit tests for the incremental-build cache bookkeeping (pure Python)."""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING

import clangquill.cache as cache_module
from clangquill.cache import CACHE_VERSION, BuildCache, file_sha256, fingerprint, hash_text

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _entry(path: Path) -> tuple[str, int]:
    """Build the ``(sha256, size_bytes)`` parse-snapshot value for ``path``."""
    return (file_sha256(path), path.stat().st_size)


def test_fingerprint_is_order_independent_but_value_sensitive() -> None:
    a = fingerprint({"x": [1, 2], "y": "z"})
    b = fingerprint({"y": "z", "x": [1, 2]})
    assert a == b
    assert a != fingerprint({"x": [2, 1], "y": "z"})


def test_file_sha256_matches_hash_text_for_text_bytes(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    assert file_sha256(path) == hash_text("hello")


def test_parse_is_current_tracks_configuration_and_contents(tmp_path: Path) -> None:
    header = tmp_path / "a.hpp"
    header.write_text("one", encoding="utf-8")
    with BuildCache.open(tmp_path / "cache") as cache:
        cache.record_parse("fp-1", {str(header): _entry(header)})

        # Same fingerprint and unchanged file -> reuse the cached parse.
        assert cache.parse_is_current("fp-1")
        # A different configuration fingerprint invalidates regardless of files.
        assert not cache.parse_is_current("fp-2")

        # Editing a tracked file invalidates the cached parse.
        header.write_text("two", encoding="utf-8")
        assert not cache.parse_is_current("fp-1")

        # A vanished dependency also invalidates it.
        header.unlink()
        assert not cache.parse_is_current("fp-1")


def test_parse_is_current_skips_hash_when_metadata_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    header = tmp_path / "a.hpp"
    header.write_text("one", encoding="utf-8")
    with BuildCache.open(tmp_path / "cache") as cache:
        cache.record_parse("fp-1", {str(header): _entry(header)})

        # With (mtime_ns, size_bytes) unchanged the fast-path must avoid reading
        # the file at all: a hash that explodes proves it is never called.
        def explode(_path: object) -> str:
            msg = "file_sha256 must not run when metadata is unchanged"
            raise AssertionError(msg)

        monkeypatch.setattr(cache_module, "file_sha256", explode)
        assert cache.parse_is_current("fp-1")


def test_parse_is_current_falls_back_to_hash_when_only_mtime_changes(tmp_path: Path) -> None:
    header = tmp_path / "a.hpp"
    header.write_text("one", encoding="utf-8")
    with BuildCache.open(tmp_path / "cache") as cache:
        cache.record_parse("fp-1", {str(header): _entry(header)})

        # A touched-but-identical file (new mtime, same bytes) defeats the
        # fast-path, but the hash comparison still recognises it as unchanged.
        stat = header.stat()
        touched_ns = stat.st_mtime_ns + 1_000_000_000
        os.utime(header, ns=(stat.st_atime_ns, touched_ns))
        assert cache.parse_is_current("fp-1")

        # The hash fallback heals the stored metadata, so a second noop now hits
        # the fast-path without re-reading the file.
        def explode(_path: object) -> str:
            msg = "metadata should have been refreshed after the hash fallback"
            raise AssertionError(msg)

        original = cache_module.file_sha256
        cache_module.file_sha256 = explode
        try:
            assert cache.parse_is_current("fp-1")
        finally:
            cache_module.file_sha256 = original

        # Same-size edit (3 bytes -> 3 bytes) still invalidates via the hash.
        header.write_text("two", encoding="utf-8")
        assert not cache.parse_is_current("fp-1")


def test_parse_is_current_false_without_tracked_files(tmp_path: Path) -> None:
    with BuildCache.open(tmp_path / "cache") as cache:
        cache.record_parse("fp", {})
        assert not cache.parse_is_current("fp")


def test_outputs_round_trip_and_replacement(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    with BuildCache.open(cache_dir) as cache:
        cache.record_outputs({"a.md": "h1", "b.md": "h2"})
    # State persists across open()s.
    with BuildCache.open(cache_dir) as cache:
        assert cache.outputs() == {"a.md": "h1", "b.md": "h2"}
        # record_outputs replaces the whole index rather than merging.
        cache.record_outputs({"a.md": "h1b"})
        assert cache.outputs() == {"a.md": "h1b"}


def test_render_round_trip_and_currency(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    with BuildCache.open(cache_dir) as cache:
        # Nothing recorded yet: never current, no summary.
        assert not cache.render_is_current("rfp-1")
        assert cache.render_summary() is None

        summary = {"symbol_count": 3, "reference_count": 1, "file_count": 2, "pages": ["a", "b"]}
        cache.record_render("rfp-1", summary)

    with BuildCache.open(cache_dir) as cache:
        # State persists and currency is fingerprint-sensitive.
        assert cache.render_is_current("rfp-1")
        assert not cache.render_is_current("rfp-2")
        assert cache.render_summary() == summary


def test_render_summary_survives_version_reset_as_absent(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    with BuildCache.open(cache_dir) as cache:
        cache.record_render("rfp", {"symbol_count": 1, "pages": []})
        cache._set_meta("cache_version", str(CACHE_VERSION + 1))  # noqa: SLF001
        cache._con.commit()  # noqa: SLF001
    # An incompatible version wipes the render bookkeeping along with the rest.
    with BuildCache.open(cache_dir) as cache:
        assert cache.render_summary() is None
        assert not cache.render_is_current("rfp")


def test_corrupted_cache_is_discarded_and_rebuilt(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # A garbage file where the SQLite database is expected must not wedge builds.
    (cache_dir / BuildCache.FILENAME).write_bytes(b"not a sqlite database at all")
    with BuildCache.open(cache_dir) as cache:
        assert cache.outputs() == {}
        cache.record_outputs({"a.md": "h1"})
    with BuildCache.open(cache_dir) as cache:
        assert cache.outputs() == {"a.md": "h1"}


def _write_v1_cache(cache_dir: Path) -> Path:
    """Create a pre-mtime ``CACHE_VERSION = 1`` cache file with the old layout.

    The v1 ``inputs`` table had only ``(path, sha256)`` — no ``mtime_ns`` /
    ``size_bytes`` — so this exercises the column-adding migration, which a row
    delete alone cannot perform.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cache_dir / BuildCache.FILENAME)
    try:
        con.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE inputs (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
            CREATE TABLE outputs (output_path TEXT PRIMARY KEY, content_hash TEXT NOT NULL);
            """,
        )
        con.execute("INSERT INTO meta(key, value) VALUES('cache_version', '1')")
        con.execute("INSERT INTO inputs(path, sha256) VALUES('/old/a.hpp', 'deadbeef')")
        con.commit()
    finally:
        con.close()
    return cache_dir


def test_v1_cache_is_migrated_to_current_schema(tmp_path: Path) -> None:
    cache_dir = _write_v1_cache(tmp_path / "cache")
    header = tmp_path / "a.hpp"
    header.write_text("one", encoding="utf-8")

    # Opening a v1 cache must rebuild the schema (not just delete rows), so the
    # new mtime_ns/size_bytes columns exist and the 4-column write path works.
    with BuildCache.open(cache_dir) as cache:
        assert cache.parse_fingerprint is None  # old inputs were discarded
        cache.record_parse("fp-1", {str(header): _entry(header)})
        assert cache.parse_is_current("fp-1")


def test_version_mismatch_resets_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    with BuildCache.open(cache_dir) as cache:
        cache.record_outputs({"a.md": "h1"})
        cache._set_meta("cache_version", str(CACHE_VERSION + 1))  # noqa: SLF001
        cache._con.commit()  # noqa: SLF001
    # Re-opening sees an incompatible version and starts from scratch.
    with BuildCache.open(cache_dir) as cache:
        assert cache.outputs() == {}
        assert cache.parse_fingerprint is None
