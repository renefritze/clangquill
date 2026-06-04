"""Unit tests for the incremental-build cache bookkeeping (pure Python)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clangquill.cache import CACHE_VERSION, BuildCache, file_sha256, fingerprint, hash_text

if TYPE_CHECKING:
    from pathlib import Path


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
        cache.record_parse("fp-1", {str(header): file_sha256(header)})

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
