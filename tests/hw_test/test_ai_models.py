"""Tests for AI models."""

from hw.ai.models import ResearchRequest, ResearchResult, ToolCall, ToolResult


def test_research_request():
    """Test ResearchRequest model."""
    request = ResearchRequest(
        comment="10uF/10V",
        footprint="C_0805_2012Metric",
        error_message="No search results found",
    )

    assert request.comment == "10uF/10V"
    assert request.footprint == "C_0805_2012Metric"
    assert request.error_message == "No search results found"


def test_research_result_success():
    """Test ResearchResult with successful result."""
    result = ResearchResult(
        jlcpcb_part_number="C12345",
        justification="Found matching 10uF capacitor with correct footprint",
        success=True,
    )

    assert result.jlcpcb_part_number == "C12345"
    assert (
        result.justification == "Found matching 10uF capacitor with correct footprint"
    )
    assert result.success is True
    assert result.error is None


def test_research_result_failure():
    """Test ResearchResult with failed result."""
    result = ResearchResult(
        jlcpcb_part_number=None,
        justification="Could not find suitable match",
        success=False,
        error="No parts with required voltage rating",
    )

    assert result.jlcpcb_part_number is None
    assert result.justification == "Could not find suitable match"
    assert result.success is False
    assert result.error == "No parts with required voltage rating"


def test_research_result_defaults():
    """Test ResearchResult with default values."""
    result = ResearchResult(
        justification="Test justification",
        success=False,
    )

    assert result.jlcpcb_part_number is None
    assert result.error is None


def test_tool_call():
    """Test ToolCall model."""
    call = ToolCall(
        tool_name="fetch_url",
        tool_input={"url": "https://example.com"},
        tool_use_id="call_abc123",
    )

    assert call.tool_name == "fetch_url"
    assert call.tool_input == {"url": "https://example.com"}
    assert call.tool_use_id == "call_abc123"


def test_tool_result():
    """Test ToolResult model."""
    result = ToolResult(
        tool_use_id="call_abc123",
        content="Successfully fetched content",
        is_error=False,
    )

    assert result.tool_use_id == "call_abc123"
    assert result.content == "Successfully fetched content"
    assert result.is_error is False


def test_tool_result_with_error():
    """Test ToolResult with error."""
    result = ToolResult(
        tool_use_id="call_abc123",
        content="Connection timeout",
        is_error=True,
    )

    assert result.tool_use_id == "call_abc123"
    assert result.content == "Connection timeout"
    assert result.is_error is True


def test_tool_result_default_error_flag():
    """Test ToolResult default is_error value."""
    result = ToolResult(
        tool_use_id="call_abc123",
        content="Some content",
    )

    assert result.is_error is False
