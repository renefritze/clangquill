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
CACHE_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Every file the last parse touched (the inputs plus their transitive
-- #include dependencies), with the content hash it had at parse time and the
-- (mtime_ns, size_bytes) metadata used as a fast-path to skip re-hashing a file
-- whose stat() is unchanged. The metadata columns are nullable: a file that
-- could not be stat'd at record time stores NULL and always takes the hash path.
CREATE TABLE IF NOT EXISTS inputs (
  path       TEXT PRIMARY KEY,
  sha256     TEXT NOT NULL,
  mtime_ns   INTEGER,
  size_bytes INTEGER
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

# Meta keys backing the noop-render skip: the fingerprint of everything that
# shapes the rendered output *given an unchanged IR* (render config plus any
# override template contents), and a small JSON summary of the last render so a
# fully unchanged build can return its counts/pages without rendering at all.
_RENDER_FINGERPRINT = "render_fingerprint"
_RENDER_SUMMARY = "render_summary"


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
        every tracked file still exists with the same content. Any added,
        removed, or edited dependency makes the cached IR stale.

        A file whose ``(st_mtime_ns, st_size)`` is unchanged from parse time is
        assumed identical and the SHA-256 read is skipped — the same fast-path
        ``make`` uses. The hash is still computed (and compared) for any file
        whose metadata moved, so a touched-but-identical file is correctly
        recognised as unchanged and a byte-edit that preserved the metadata
        would still be caught on the next metadata change.
        """
        if self.parse_fingerprint != parse_fingerprint:
            return False
        rows = self._con.execute("SELECT path, sha256, mtime_ns, size_bytes FROM inputs").fetchall()
        if not rows:
            return False
        for row in rows:
            path = row["path"]
            try:
                stat = Path(path).stat()
            except OSError:
                return False
            if (
                row["mtime_ns"] is not None
                and row["size_bytes"] is not None
                and stat.st_mtime_ns == row["mtime_ns"]
                and stat.st_size == row["size_bytes"]
            ):
                continue  # metadata unchanged — skip the hash read
            try:
                if file_sha256(path) != row["sha256"]:
                    return False
            except OSError:
                return False
        return True

    def record_parse(self, parse_fingerprint: str, files: Mapping[str, str]) -> None:
        """Persist the fingerprint and ``{path: sha256}`` of a fresh parse.

        Each path is ``stat``'d so the ``(mtime_ns, size_bytes)`` fast-path in
        :meth:`parse_is_current` can later skip re-hashing unchanged files. A
        path that cannot be stat'd records ``NULL`` metadata and always falls
        back to the hash comparison.
        """
        self._set_meta(_PARSE_FINGERPRINT, parse_fingerprint)
        self._con.execute("DELETE FROM inputs")
        self._con.executemany(
            "INSERT OR REPLACE INTO inputs(path, sha256, mtime_ns, size_bytes) VALUES(?, ?, ?, ?)",
            [(path, sha, *self._stat_metadata(path)) for path, sha in files.items()],
        )
        self._con.commit()

    # -- render bookkeeping ---------------------------------------------------

    @property
    def render_fingerprint(self) -> str | None:
        """The fingerprint of the render config/templates that last rendered."""
        return self._meta(_RENDER_FINGERPRINT)

    def render_summary(self) -> dict[str, object] | None:
        """Return the cached summary of the last render, or ``None``.

        The summary carries the symbol/reference/file counts and the ordered
        page stems so a noop build can reproduce its :class:`BuildResult` without
        opening the store or running Jinja.
        """
        raw = self._meta(_RENDER_SUMMARY)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def render_is_current(self, render_fingerprint: str) -> bool:
        """Whether the last render still applies to ``render_fingerprint``.

        ``True`` only when the fingerprint matches *and* a summary was stored, so
        a cache predating this optimisation never short-circuits a render.
        Callers must separately confirm the IR itself is unchanged (a cache-hit
        parse) before trusting this — the fingerprint deliberately omits the IR.
        """
        return self.render_fingerprint == render_fingerprint and self.render_summary() is not None

    def record_render(self, render_fingerprint: str, summary: Mapping[str, object]) -> None:
        """Persist the render fingerprint and summary of a fresh render."""
        self._set_meta(_RENDER_FINGERPRINT, render_fingerprint)
        self._set_meta(_RENDER_SUMMARY, json.dumps(dict(summary)))
        self._con.commit()

    @staticmethod
    def _stat_metadata(path: str) -> tuple[int | None, int | None]:
        """Return ``(mtime_ns, size_bytes)`` for ``path``, or ``(None, None)``."""
        try:
            stat = Path(path).stat()
        except OSError:
            return (None, None)
        return (stat.st_mtime_ns, stat.st_size)

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
