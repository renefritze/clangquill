"""Helpers for reasoning about the libclang the core was built against.

The compiled core exposes the backend version as a free-form string via
``clangquill._core.libclang_version()`` (the result of ``clang_getClangVersion``,
e.g. ``"clang version 18.1.3"`` or ``"Ubuntu clang version 18.1.3"``). The major
number decides which C++ standards parse, so docs/tests gate features on it
through this single parser rather than duplicating the regex.
"""

from __future__ import annotations

import re

from clangquill import _core

# Anchor on the word "version" so we read the real version (e.g. "clang version
# 18.1.3") rather than an incidental number elsewhere in the string.
_VERSION_RE = re.compile(r"version\s+(\d+)\.")


def libclang_major() -> int | None:
    """Return the major version of the linked libclang, or ``None``.

    ``None`` is returned when the core was built without libclang or the version
    string cannot be parsed, so callers can treat "unknown" the same as "old".
    """
    if not _core.have_libclang():
        return None
    match = _VERSION_RE.search(_core.libclang_version())
    return int(match.group(1)) if match else None
