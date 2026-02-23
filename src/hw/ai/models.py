"""Data models for AI research functionality."""

from typing import Optional

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """Request to research a component that couldn't be found."""

    comment: str = Field(
        description="Original comment/value from BOM (e.g., '10uF/10V', '100nF')"
    )
    footprint: str = Field(
        description="KiCad footprint name (e.g., 'C_0805_2012Metric')"
    )
    error_message: str = Field(description="Error message from initial lookup attempt")


class ResearchResult(BaseModel):
    """Result of AI research for a component."""

    jlcpcb_part_number: Optional[str] = Field(
        default=None, description="JLCPCB C-number if found (e.g., 'C12345')"
    )
    justification: str = Field(
        description="Explanation of the research and why this part was selected"
    )
    success: bool = Field(description="Whether a suitable part was found")
    error: Optional[str] = Field(
        default=None, description="Error message if research failed"
    )


class ToolCall(BaseModel):
    """Represents a tool call in the Anthropic conversation."""

    tool_name: str = Field(description="Name of the tool being called")
    tool_input: dict = Field(description="Input parameters for the tool")
    tool_use_id: str = Field(description="Unique ID for this tool use")


class ToolResult(BaseModel):
    """Result from executing a tool."""

    tool_use_id: str = Field(
        description="ID of the tool use this result corresponds to"
    )
    content: str = Field(description="The result content")
    is_error: bool = Field(default=False, description="Whether this is an error result")
