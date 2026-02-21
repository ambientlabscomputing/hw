import click

from hw.circuits import circuits
from hw.utils.logger import setup_logger

setup_logger()


@click.group()
def main() -> None:
    """hw – hardware tooling CLI."""


main.add_command(circuits)
