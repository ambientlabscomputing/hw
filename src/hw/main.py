import click

from hw.utils.logger import setup_logger

setup_logger()


@click.command()
def main():
    click.echo("Hello, World!")
