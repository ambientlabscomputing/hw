"""AI agent for researching electronic components."""

import asyncio
import re
from typing import Any

import anthropic
import click
from loguru import logger

from hw.ai.config import AiConfig, get_default_mcp_servers
from hw.ai.mcp_client import McpManager
from hw.ai.models import ResearchRequest, ResearchResult

PRIMARY_MODEL = "claude-sonnet-4-6"
ESCALATION_MODEL = "claude-opus-4-6"
_RATE_LIMIT_RETRIES = 8
_RATE_LIMIT_DEFAULT_DELAY = 5  # seconds — used when Anthropic doesn't send retry-after

# Only expose the tools the agent actually needs — tool definitions count against
# your input-token budget on every single API call.
BROWSER_TOOLS = {
    "browser_navigate",
    "browser_network_requests",
    "browser_snapshot",
    "browser_wait_for",
}

SYSTEM_PROMPT = """\
You are an expert electronics engineer sourcing SMD components on JLCPCB.

## Token-efficient search strategy

JLCPCB's search page fires an XHR to its internal API. Capturing that JSON is
much smaller than parsing the page snapshot. Do this:

1. Call browser_navigate to the search URL.
2. Call browser_network_requests to get all XHR/fetch responses.
3. Find the response whose URL contains "componentSearch" — it's a compact JSON
   list with fields: lcscPart, componentTypeEn, stockCount, lcscGoodsType, package.
4. Parse that JSON to find your match. Only call browser_snapshot if no network
   request contains the parts data.

Search URL pattern:
  https://jlcpcb.com/parts/componentSearch?searchTxt=<keywords>&pageSize=50&currentPage=1

## KiCad footprint → JLCPCB package name

  C_0402_1005Metric → 0402    C_0805_2012Metric → 0805    C_1206_3216Metric → 1206
  R_0402_1005Metric → 0402    R_0805_2012Metric → 0805    R_1206_3216Metric → 1206
  L_0402_1005Metric → 0402    L_1210_3225Metric → 1210     L_1812_4532Metric → 1812

## Search strategy (try in order, stop when matched)

1. "<value> <package>"          e.g. "10uF 0805", "27 ohm 0402"
2. INDUCTORS use R-notation:   2.2µH → "2R2 1210",  4.7µH → "4R7 1210",  1µH → "1R0"
3. Value alone:                "2.2uH inductor"
4. Known mfr prefix:           "NLV32T 2R2"
Give up after 4 queries.

## Selection rules

1. Package MUST match exactly (0805 ≠ 0603, 1210 ≠ 1812)
2. stockCount > 10
3. Prefer lcscGoodsType == "base" (Basic part, no surcharge)
4. Capacitors: voltage ≥ spec (default 10 V)
5. Resistors: ±1% tolerance preferred

## Output

Last line of your response must be exactly:
  JLCPCB_PART: C<number>
If nothing found after 4 searches, explain why — do NOT output JLCPCB_PART."""


async def _run_agent_loop(
    request: ResearchRequest,
    mcp: McpManager,
    tools: list[dict[str, Any]],
    client: anthropic.AsyncAnthropic,
    model: str = PRIMARY_MODEL,
) -> ResearchResult:
    """Run the Anthropic agentic loop for one research request."""
    user_message = (
        "Find a JLCPCB part for this component:\n"
        f"- Value/Comment: {request.comment}\n"
        f"- Required KiCad Footprint: {request.footprint}\n"
        f"- Previous lookup error: {request.error_message}\n\n"
        "Search jlcpcb.com/parts and return the C-number with justification."
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for iteration in range(15):
        logger.debug(f"[{request.comment}] Agent iteration {iteration + 1}/10")

        api_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        }
        if tools:
            api_kwargs["tools"] = tools

        response = None
        for attempt in range(_RATE_LIMIT_RETRIES):
            try:
                response = await client.messages.create(**api_kwargs)
                break
            except anthropic.RateLimitError as e:
                if attempt + 1 == _RATE_LIMIT_RETRIES:
                    raise
                # Honour the retry-after header Anthropic sends; fall back to 5 s
                try:
                    delay = int(
                        e.response.headers.get("retry-after", _RATE_LIMIT_DEFAULT_DELAY)
                    )
                except (AttributeError, ValueError):
                    delay = _RATE_LIMIT_DEFAULT_DELAY
                logger.warning(
                    f"[{request.comment}] Rate limit "
                    f"(attempt {attempt + 1}/{_RATE_LIMIT_RETRIES}), "
                    f"waiting {delay}s (retry-after header)..."
                )
                click.echo(
                    f"  ⏳ Rate limit — waiting {delay}s before retry...", err=True
                )
                await asyncio.sleep(delay)
        assert response is not None

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = "\n".join(b.text for b in response.content if b.type == "text")
            match = re.search(r"JLCPCB_PART:\s*(C\d+)", text)
            if match:
                logger.info(f"[{request.comment}] Found part: {match.group(1)}")
                return ResearchResult(
                    jlcpcb_part_number=match.group(1),
                    justification=text,
                    success=True,
                )
            logger.warning(f"[{request.comment}] Agent finished but found no C-number")
            return ResearchResult(
                jlcpcb_part_number=None,
                justification=text,
                success=False,
            )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                logger.info(f"[{request.comment}] Tool call: {block.name}")
                try:
                    result = await mcp.call_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
                except Exception as exc:
                    logger.error(f"[{request.comment}] Tool {block.name} failed: {exc}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {exc}",
                            "is_error": True,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        logger.warning(
            f"[{request.comment}] Unexpected stop reason: {response.stop_reason}"
        )
        return ResearchResult(
            jlcpcb_part_number=None,
            justification=f"Agent stopped unexpectedly: {response.stop_reason}",
            success=False,
        )

    return ResearchResult(
        jlcpcb_part_number=None,
        justification="Agent reached maximum iteration limit without finding a part",
        success=False,
    )


async def _research_all_async(
    requests: list[ResearchRequest],
    config: AiConfig,
    on_complete: Any = None,
) -> list[ResearchResult]:
    """Research all failed parts in a single shared MCP session."""
    mcp_servers = config.mcp_servers or get_default_mcp_servers()
    results: list[ResearchResult] = []

    try:
        async with McpManager(mcp_servers) as mcp:
            all_tools = await mcp.get_tools_for_anthropic()
            # Filter to only the tools the agent needs (cuts ~80% of token overhead)
            tools = [t for t in all_tools if t["name"] in BROWSER_TOOLS]
            if tools:
                logger.info(
                    f"Using {len(tools)}/{len(all_tools)} "
                    f"MCP tools: {[t['name'] for t in tools]}"
                )
            else:
                logger.warning(
                    "No MCP tools available " "— responses will be text-only"
                )

            # AsyncAnthropic is required inside a running event
            # loop (sync client conflicts)
            client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

            for request in requests:
                try:
                    result = await _run_agent_loop(
                        request, mcp, tools, client, model=PRIMARY_MODEL
                    )
                    # Escalate to opus if sonnet couldn't find the part
                    if not result.success:
                        logger.info(
                            f"[{request.comment}] Sonnet failed, "
                            f"escalating to {ESCALATION_MODEL}"
                        )
                        click.echo(
                            f"  ↑ Escalating to {ESCALATION_MODEL} "
                            f"for {request.comment}...",
                            err=True,
                        )
                        result = await _run_agent_loop(
                            request, mcp, tools, client, model=ESCALATION_MODEL
                        )
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error(
                        f"[{request.comment}] Agent loop error: {exc}", exc_info=True
                    )
                    result = ResearchResult(
                        jlcpcb_part_number=None,
                        justification="",
                        success=False,
                        error=str(exc),
                    )

                results.append(result)
                if on_complete is not None:
                    on_complete(request, result)
                # Brief pause between parts to stay under the token-per-minute limit
                if request is not requests[-1]:
                    await asyncio.sleep(5)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        # anyio TaskGroup teardown can raise BaseExceptionGroup — surface and continue
        logger.error(f"MCP session error: {exc}", exc_info=True)
        click.echo(f"\n❌ AI session error: {exc}", err=True)

    return results


def research_all_components(
    requests: list[ResearchRequest],
    config: AiConfig,
    on_complete: Any = None,
) -> list[ResearchResult]:
    """
    Synchronous entry point: research a batch of components.

    MCP servers start once and are shared across all requests.

    Args:
        requests: Parts to research.
        config: AI configuration.
        on_complete: Optional callable(request, result) called after each part.

    Returns:
        List of ResearchResult in the same order as requests.
    """
    return asyncio.run(_research_all_async(requests, config, on_complete))
