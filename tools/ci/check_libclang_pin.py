"""Fail when a newer LLVM release than the pinned one ships both Linux arches.

The pin lives in ``tools/ci/fetch-libclang.sh`` (``LLVM_VERSION`` default) and is
mirrored by the wheel workflows. This is run on a schedule (see
``.github/workflows/libclang-pin-check.yml``); network/API errors are treated as
non-fatal so a transient blip never raises a false alarm. It only fails when a
strictly newer stable release exists *and* ships both the X64 and ARM64 Linux
packages clangquill bundles.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

RELEASES_URL = "https://api.github.com/repos/llvm/llvm-project/releases?per_page=40"
FETCH_SCRIPT = Path(__file__).parent / "fetch-libclang.sh"
_STABLE_TAG = re.compile(r"^llvmorg-(\d+)\.(\d+)\.(\d+)$")


def pinned_version() -> str:
    try:
        text = FETCH_SCRIPT.read_text(encoding="utf-8")
    except FileNotFoundError:
        msg = f"could not find fetch-libclang.sh at {FETCH_SCRIPT}"
        raise SystemExit(msg) from None
    match = re.search(r"LLVM_VERSION:-([0-9]+\.[0-9]+\.[0-9]+)", text)
    if not match:
        msg = "could not find pinned LLVM_VERSION in fetch-libclang.sh"
        raise SystemExit(msg)
    return match.group(1)


def _ver_tuple(ver: str) -> tuple[int, int, int]:
    major, minor, patch = ver.split(".")
    return int(major), int(minor), int(patch)


def _has_both_linux_arches(assets: list[str], ver: str) -> bool:
    return f"LLVM-{ver}-Linux-X64.tar.xz" in assets and f"LLVM-{ver}-Linux-ARM64.tar.xz" in assets


def latest_with_both_arches(releases: list[dict]) -> str | None:
    """Return the highest stable LLVM version that ships both Linux arch tarballs."""
    best: tuple[int, int, int] | None = None
    best_str: str | None = None
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        match = _STABLE_TAG.match(rel.get("tag_name") or "")
        if not match:
            continue
        ver = ".".join(match.groups())
        raw_assets = rel.get("assets") or []
        assets = [a.get("name") or "" for a in raw_assets if isinstance(a, dict)]
        if not _has_both_linux_arches(assets, ver):
            continue
        candidate = _ver_tuple(ver)
        if best is None or candidate > best:
            best, best_str = candidate, ver
    return best_str


def fetch_releases() -> list[dict]:
    req = urllib.request.Request(  # noqa: S310 (hardcoded https GitHub API URL)
        RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "clangquill-pin-check",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.load(resp)


def main() -> int:
    pin = pinned_version()
    try:
        releases = fetch_releases()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"::warning::could not query LLVM releases ({exc}); skipping pin check")
        return 0

    if not isinstance(releases, list):
        print("::warning::unexpected response format from LLVM releases API; skipping")
        return 0

    latest = latest_with_both_arches(releases)
    if latest is None:
        print("::warning::no LLVM release with both Linux arches found; skipping")
        return 0

    print(f"pinned libclang: {pin}; latest with both Linux arches: {latest}")
    if _ver_tuple(latest) > _ver_tuple(pin):
        print(
            f"::error::A newer libclang ({latest}) ships both Linux arch tarballs. "
            f"Bump LLVM_VERSION from {pin} to {latest} in tools/ci/fetch-libclang.sh "
            f"and the wheel workflows (wheels.yml, deploy.yml, test_deploy.yml).",
        )
        return 1

    print("libclang pin is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
