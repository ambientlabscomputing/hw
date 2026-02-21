import click

from hw.circuits.kicad.convert.command import convert


@click.group()
def kicad() -> None:
    """KiCad-related commands."""


kicad.add_command(convert)
