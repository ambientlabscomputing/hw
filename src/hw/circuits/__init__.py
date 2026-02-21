import click

from hw.circuits.kicad import kicad


@click.group()
def circuits() -> None:
    """KiCad and other circuit-related commands."""


circuits.add_command(kicad)
