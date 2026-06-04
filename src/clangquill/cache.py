"""The incremental-build cache: parse-skip and per-output render tracking.

clangquill caches two things between runs, both under the configured
``clangquill_cache_dir``:

* the SQLite IR (``clangquill.sqlite``), so an unchanged build can reuse the
  previous parse instead of invoking libclang again; and
* a small bookkeeping database (:data:`BuildCache.FILENAME`) recording the
  fingerprint of the inputs that produced that IR and the content hash of every
  output page that was written.

The bookkeeping database is deliberately separate from the IR: the IR is
rebuilt wholesale on every parse, so anything that must survive a re-parse
(the previous run's output hashes) cannot live inside it.

This module is pure Python on top of :mod:`sqlite3` and :mod:`hashlib`; the
heavy lifting (parsing, content hashing of symbols) happens elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# Bump when the cache schema/semantics below change incompatibly; a mismatch
# transparently discards the old cache and forces a full rebuild.
CACHE_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Every file the last parse touched (the inputs plus their transitive
-- #include dependencies), with the content hash it had at parse time.
CREATE TABLE IF NOT EXISTS inputs (
  path   TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL
);

-- Every page the last render wrote, with the hash of its rendered content.
CREATE TABLE IF NOT EXISTS outputs (
  output_path  TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL
);
"""

# Meta key holding the fingerprint of the parse-affecting configuration (compile
# args, std, defines, the resolved input set, toolchain version). When this
# changes the cached IR is stale regardless of file contents.
_PARSE_FINGERPRINT = "parse_fingerprint"


def file_sha256(path: str | Path) -> str:
    """Return the hex SHA-256 of ``path``'s bytes, matching the C++ digest.

    Raises :class:`OSError` if the file cannot be read; callers treat that as a
    changed/absent dependency.
    """
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_text(text: str) -> str:
    """Return the hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(payload: Mapping[str, object]) -> str:
    """Hash a JSON-able mapping into a stable fingerprint string.

    Keys are sorted so the digest is independent of insertion order.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hash_text(blob)


class BuildCache:
    """Read/write bookkeeping for incremental builds under a cache directory."""

    #: Filename of the bookkeeping database within the cache directory.
    FILENAME = "clangquill-cache.sqlite"

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Wrap an open connection (prefer :meth:`open`)."""
        self._con = connection
        self._con.row_factory = sqlite3.Row

    @classmethod
    @contextmanager
    def open(cls, cache_dir: str | Path) -> Iterator[BuildCache]:
        """Open (creating if needed) the cache under ``cache_dir`` and yield it.

        A cache written by an incompatible :data:`CACHE_VERSION` is reset so a
        stale layout never produces wrong incremental decisions.
        """
        directory = Path(cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        cache_file = directory / cls.FILENAME
        try:
            con = sqlite3.connect(cache_file)
            con.executescript(_SCHEMA)
        except sqlite3.DatabaseError:
            # A corrupted cache (interrupted write, bad disk) must not wedge every
            # future build: discard it and start clean rather than propagate.
            with suppress(sqlite3.Error):
                con.close()
            cache_file.unlink(missing_ok=True)
            con = sqlite3.connect(cache_file)
            con.executescript(_SCHEMA)
        try:
            cache = cls(con)
            if cache._meta("cache_version") != str(CACHE_VERSION):
                cache.reset()
                cache._set_meta("cache_version", str(CACHE_VERSION))
                con.commit()
            yield cache
        finally:
            con.close()

    # -- meta -----------------------------------------------------------------

    def _meta(self, key: str) -> str | None:
        row = self._con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._con.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def reset(self) -> None:
        """Forget everything (used on a version mismatch)."""
        self._con.execute("DELETE FROM meta")
        self._con.execute("DELETE FROM inputs")
        self._con.execute("DELETE FROM outputs")

    # -- parse bookkeeping ----------------------------------------------------

    @property
    def parse_fingerprint(self) -> str | None:
        """The configuration fingerprint of the cached parse, or ``None``."""
        return self._meta(_PARSE_FINGERPRINT)

    def tracked_files(self) -> dict[str, str]:
        """Return ``{path: sha256}`` for every file the cached parse touched."""
        return {row["path"]: row["sha256"] for row in self._con.execute("SELECT path, sha256 FROM inputs")}

    def parse_is_current(self, parse_fingerprint: str) -> bool:
        """Whether the cached parse still matches the inputs.

        ``True`` only when the configuration fingerprint is unchanged *and*
        every tracked file still exists with the same content hash. Any added,
        removed, or edited dependency makes the cached IR stale.
        """
        if self.parse_fingerprint != parse_fingerprint:
            return False
        tracked = self.tracked_files()
        if not tracked:
            return False
        for path, sha in tracked.items():
            try:
                if file_sha256(path) != sha:
                    return False
            except OSError:
                return False
        return True

    def record_parse(self, parse_fingerprint: str, files: Mapping[str, str]) -> None:
        """Persist the fingerprint and ``{path: sha256}`` of a fresh parse."""
        self._set_meta(_PARSE_FINGERPRINT, parse_fingerprint)
        self._con.execute("DELETE FROM inputs")
        self._con.executemany(
            "INSERT OR REPLACE INTO inputs(path, sha256) VALUES(?, ?)",
            list(files.items()),
        )
        self._con.commit()

    # -- output bookkeeping ---------------------------------------------------

    def outputs(self) -> dict[str, str]:
        """Return ``{output_path: content_hash}`` from the last render."""
        return {
            row["output_path"]: row["content_hash"]
            for row in self._con.execute("SELECT output_path, content_hash FROM outputs")
        }

    def record_outputs(self, outputs: Mapping[str, str]) -> None:
        """Replace the stored output index with ``{output_path: content_hash}``."""
        self._con.execute("DELETE FROM outputs")
        self._con.executemany(
            "INSERT OR REPLACE INTO outputs(output_path, content_hash) VALUES(?, ?)",
            list(outputs.items()),
        )
        self._con.commit()


__all__ = [
    "CACHE_VERSION",
    "BuildCache",
    "file_sha256",
    "fingerprint",
    "hash_text",
]
