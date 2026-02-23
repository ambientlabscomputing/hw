import click

from hw.circuits import circuits
from hw.config import config_group
from hw.init import init_command
from hw.utils.logger import setup_logger

setup_logger()


@click.group()
def main() -> None:
    """hw – hardware tooling CLI."""


main.add_command(circuits)
main.add_command(config_group)
main.add_command(init_command)
