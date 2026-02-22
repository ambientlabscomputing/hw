import click

from hw.circuits.jlcpcb import jlcpcb
from hw.circuits.kicad import kicad


@click.group()
def circuits() -> None:
    """KiCad and other circuit-related commands."""


circuits.add_command(jlcpcb)
circuits.add_command(kicad)
