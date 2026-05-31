"""Top-level package for clangquill."""

__author__ = """ René Fritze"""
__email__ = " rene@fritze.me"

try:
    from . import _version
    __version__ = _version.__version__
except ImportError as e:
    print(f"version file could not be imported: {e}") #  noqa: T201
    __version__ = "unknown"
