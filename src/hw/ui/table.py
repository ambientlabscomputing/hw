"""Generic table rendering component using rich."""

from typing import Any

from rich.console import Console
from rich.table import Table as RichTable


class TableColumn:
    """Configuration for a table column."""

    def __init__(
        self,
        name: str,
        style: str | None = None,
        justify: str = "left",
        no_wrap: bool = False,
    ):
        self.name = name
        self.style = style
        self.justify = justify
        self.no_wrap = no_wrap


class Table:
    """Generic table component for CLI output.

    Example usage:
        columns = [
            TableColumn("Name", style="bold cyan"),
            TableColumn("Value", justify="right"),
            TableColumn("Status", style="green"),
        ]
        table = Table("My Table", columns)
        table.add_row(["Item 1", "100", "Active"])
        table.add_row(["Item 2", "200", "Inactive"], style="dim")
        table.render()
    """

    def __init__(
        self,
        title: str | None = None,
        columns: list[TableColumn] | None = None,
        show_header: bool = True,
        show_lines: bool = False,
    ):
        """Initialize a table.

        Args:
            title: Optional table title
            columns: List of TableColumn definitions
            show_header: Whether to show column headers
            show_lines: Whether to show lines between rows
        """
        self.title = title
        self.columns = columns or []
        self.show_header = show_header
        self.show_lines = show_lines
        self.rows: list[tuple[list[Any], str | None]] = []

    def add_row(self, values: list[Any], style: str | None = None) -> None:
        """Add a row to the table.

        Args:
            values: List of cell values (must match column count)
            style: Optional style for the entire row
        """
        self.rows.append((values, style))

    def _build_rich_table(self) -> RichTable:
        """Build a rich.Table object from the configuration."""
        table = RichTable(
            title=self.title,
            show_header=self.show_header,
            show_lines=self.show_lines,
        )

        # Add columns
        for col in self.columns:
            table.add_column(
                col.name,
                style=col.style,
                justify=col.justify,  # type: ignore
                no_wrap=col.no_wrap,
            )

        # Add rows
        for values, row_style in self.rows:
            str_values = [str(v) for v in values]
            table.add_row(*str_values, style=row_style)

        return table

    def render(self) -> None:
        """Render the table to the console."""
        console = Console()
        table = self._build_rich_table()
        console.print(table)

    def to_string(self) -> str:
        """Return the table as a string (useful for testing).

        Returns:
            The rendered table as a string
        """
        console = Console(width=120)
        table = self._build_rich_table()
        with console.capture() as capture:
            console.print(table)
        return capture.get()
