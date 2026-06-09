"""Tests for `clangquill` package."""

import re

from typer.testing import CliRunner

import clangquill
from clangquill import cli

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _condense(text: str) -> str:
    """Strip ANSI styling and all whitespace from CLI help output.

    Typer renders ``--help`` through Rich as a panel whose width depends on the
    environment; in a non-tty CI shell long option names can wrap or be split by
    style spans. Collapsing styling and whitespace makes substring checks robust
    to that layout while still proving the option is present.
    """
    return "".join(_ANSI_RE.sub("", text).split())


def test_version():
    assert clangquill.__version__


def test_import():
    pass


def test_command_line_interface():
    """The typer app exposes a documented ``build`` command."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "build" in _condense(result.output)

    build_help = runner.invoke(cli.app, ["build", "--help"])
    assert build_help.exit_code == 0
    assert "--output-dir" in _condense(build_help.output)


def test_version_flag():
    """``--version`` reports the package version and exits cleanly."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    out = _condense(result.output)
    assert f"clangquill{clangquill.__version__}" in out
    # The libclang line is always emitted (linked version or the stub note).
    assert "libclang" in out


def test_build_requires_inputs():
    """Invoking ``build`` with no inputs fails with usage help."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["build"])
    assert result.exit_code != 0
