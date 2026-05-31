"""Tests for `clangquill` package."""

from click.testing import CliRunner

import clangquill
from clangquill import cli


def test_version():
    assert clangquill.__version__


def test_import():
    pass


def test_command_line_interface():
    """Test the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli.main)
    assert result.exit_code == 0
    assert "clangquill.cli.main" in result.output
    help_result = runner.invoke(cli.main, ["--help"])
    assert help_result.exit_code == 0
    assert "--help  Show this message and exit." in help_result.output
