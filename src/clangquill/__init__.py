"""Top-level package for clangquill."""

from importlib.metadata import PackageNotFoundError, version

__author__ = "René Fritze"
__email__ = "rene@fritze.me"

try:
    __version__ = version("clangquill")
except PackageNotFoundError:  # package is not installed
    __version__ = "unknown"

__all__ = ["__version__"]
