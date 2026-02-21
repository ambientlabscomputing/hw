import click


def _read_input(input_file: str) -> None:
    """Dummy: read input CSV file."""


def _write_output(output_file: str) -> None:
    """Dummy: write output CSV file."""


@click.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", type=click.Path())
def convert(input_file: str, output_file: str) -> None:
    """Convert a KiCad CSV file to the output format."""
    _read_input(input_file)
    _write_output(output_file)
    click.echo(f"Converted {input_file} -> {output_file}")
