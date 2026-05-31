"""Tests for `clangquill` package."""
from click.testing import CliRunner


def test_version():
    import clangquill
    assert clangquill.__version__


def test_import():
    import clangquill


def test_command_line_interface():
    """Test the CLI."""
    from clangquill import cli
    runner = CliRunner()
    result = runner.invoke(cli.main)
    assert result.exit_code == 0
    assert 'clangquill.cli.main' in result.output
    help_result = runner.invoke(cli.main, ['--help'])
    assert help_result.exit_code == 0
    assert '--help  Show this message and exit.' in help_result.output
