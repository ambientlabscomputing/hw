"""Unit tests for the Table UI component."""

from hw.ui.table import Table, TableColumn


def test_table_basic_rendering():
    """Test basic table rendering."""
    columns = [
        TableColumn("Name"),
        TableColumn("Value"),
    ]

    table = Table("Test Table", columns)
    table.add_row(["Item 1", "100"])
    table.add_row(["Item 2", "200"])

    output = table.to_string()

    assert "Test Table" in output
    assert "Name" in output
    assert "Value" in output
    assert "Item 1" in output
    assert "100" in output


def test_table_no_title():
    """Test table without a title."""
    columns = [TableColumn("Col1")]
    table = Table(columns=columns)
    table.add_row(["Value"])

    output = table.to_string()

    assert "Col1" in output
    assert "Value" in output


def test_table_empty():
    """Test table with no rows."""
    columns = [TableColumn("Col1"), TableColumn("Col2")]
    table = Table("Empty Table", columns)

    output = table.to_string()

    assert "Empty Table" in output
    assert "Col1" in output
    assert "Col2" in output


def test_table_with_styled_row():
    """Test table with row styling."""
    columns = [TableColumn("Status")]
    table = Table(columns=columns)
    table.add_row(["Success"], style="green")
    table.add_row(["Error"], style="red")

    # Just verify it doesn't crash - styling is visual
    output = table.to_string()
    assert "Success" in output
    assert "Error" in output
