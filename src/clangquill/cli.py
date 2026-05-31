"""Console script for clangquill."""
import sys
import click


@click.command()
def main(args=None):
    """Console script for clangquill."""
    click.echo(
        "Replace this message by putting your code into "
        "clangquill.cli.main"
    )
    click.echo("See click documentation at https://click.palletsprojects.com/")
    print(f"Gotta use the args: {args}") # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
