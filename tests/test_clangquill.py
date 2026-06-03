"""Tests for `clangquill` package."""

from typer.testing import CliRunner

import clangquill
from clangquill import cli


def test_version():
    assert clangquill.__version__


def test_import():
    pass


def test_command_line_interface():
    """The typer app exposes a documented ``build`` command."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "build" in result.output

    build_help = runner.invoke(cli.app, ["build", "--help"])
    assert build_help.exit_code == 0
    assert "--output-dir" in build_help.output


def test_build_requires_inputs():
    """Invoking ``build`` with no inputs fails with usage help."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["build"])
    assert result.exit_code != 0
