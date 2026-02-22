import click

from hw.circuits.jlcpcb.bom_lookup.command import bom_lookup


@click.group()
def jlcpcb() -> None:
    """JLCPCB-related commands."""


jlcpcb.add_command(bom_lookup)
