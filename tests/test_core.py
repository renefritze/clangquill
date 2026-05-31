"""Tests for the compiled `clangquill._core` extension (M1)."""

from clangquill import _core


def test_core_importable():
    assert _core.__core_version__


def test_have_libclang_is_bool():
    assert isinstance(_core.have_libclang(), bool)


def test_libclang_version_matches_backend():
    version = _core.libclang_version()
    if _core.have_libclang():
        # When linked, the C API call must return a real version string.
        assert "clang" in version.lower()
    else:
        assert version == ""
