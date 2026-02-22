"""Part resolution logic for selecting the best component from search results."""

import re

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.models import MIN_STOCK, JlcpcbSearchResult


def _normalize_footprint(footprint: str) -> set[str]:
    """Extract normalized footprint identifiers.

    Examples:
        "C_0402_1005Metric" -> {"0402", "1005"}
        "R_0805_2012Metric" -> {"0805", "2012"}
        "ESP32-S3-WROOM-1" -> {"esp32", "s3", "wroom"}

    Args:
        footprint: Raw footprint string

    Returns:
        Set of normalized footprint tokens
    """
    # Extract all 4-digit metric codes (like 0402, 0805, 1206, etc.)
    metric_codes = re.findall(r"\d{4}", footprint)

    # Extract alphanumeric tokens (lowercase for comparison)
    tokens = re.findall(r"[a-z0-9]+", footprint.lower())

    result = set(metric_codes + tokens)
    logger.debug(f"Normalized footprint '{footprint}' -> {result}")
    return result


def _footprint_matches(package: str | None, footprint: str) -> bool:
    """Check if a package matches the expected footprint.

    Args:
        package: Package string from API response
        footprint: Expected footprint from BOM

    Returns:
        True if package matches footprint
    """
    if not package:
        return False

    footprint_tokens = _normalize_footprint(footprint)
    package_tokens = _normalize_footprint(package)

    # Check for overlap in tokens
    overlap = footprint_tokens & package_tokens

    # If there's significant overlap (at least one common token), consider it a match
    matches = len(overlap) > 0

    if matches:
        logger.debug(f"Footprint match: {package} <-> {footprint} (overlap: {overlap})")

    return matches


def _score_candidate(candidate: JlcpcbSearchResult, footprint: str) -> float:
    """Score a candidate part for ranking.

    Higher score is better. Scoring criteria:
    - JLCPCB source: +1000
    - Footprint match: +500
    - Stock (normalized): +0-100
    - Lower price (if available): +0-50

    Args:
        candidate: Search result to score
        footprint: Expected footprint

    Returns:
        Numeric score (higher is better)
    """
    score = 0.0

    # Prefer JLCPCB over LCSC
    if candidate.source == "jlcpcb":
        score += 1000

    # Reward footprint match
    if _footprint_matches(candidate.package, footprint):
        score += 500

    # Reward high stock (normalized to 0-100 range)
    # Assume 1000+ stock is excellent, scale proportionally
    stock_score = min(100, (candidate.stock / 1000) * 100)
    score += stock_score

    # Reward lower price (inverse relationship)
    if candidate.price is not None and candidate.price > 0:
        # Lower price = higher score (cap at 50 points)
        # For typical components < $10, this gives reasonable scaling
        price_score = min(50, 50 / (1 + candidate.price))
        score += price_score

    logger.debug(
        f"Scored {candidate.lcsc_part}: {score:.1f} "
        f"(source={candidate.source}, stock={candidate.stock}, price={candidate.price})"
    )

    return score


def resolve_part(
    comment: str, footprint: str, candidates: list[JlcpcbSearchResult]
) -> tuple[JlcpcbSearchResult | None, str | None]:
    """Select the best part from search results.

    Algorithm:
    1. Filter out parts with insufficient stock
    2. Filter by footprint match (if possible to determine)
    3. Rank remaining candidates by score
    4. Select the top-ranked candidate

    Args:
        comment: Part comment/value
        footprint: Expected footprint
        candidates: List of search results

    Returns:
        Tuple of (selected_part, error_message)
        - If successful: (JlcpcbSearchResult, None)
        - If failed: (None, error_description)
    """
    logger.info(
        f"Resolving part: {comment} ({footprint}) from {len(candidates)} candidates"
    )

    if not candidates:
        return None, "No search results found"

    # Step 1: Filter by stock
    in_stock = [c for c in candidates if c.stock >= MIN_STOCK]

    if not in_stock:
        max_stock = max(c.stock for c in candidates)
        return (
            None,
            f"All candidates out of stock (max available: \
{max_stock}, need: {MIN_STOCK})",
        )

    logger.debug(f"{len(in_stock)}/{len(candidates)} candidates have sufficient stock")

    # Step 2: Try to filter by footprint match
    # If we can match footprint, prefer those; otherwise use all in-stock candidates
    footprint_matched = [
        c for c in in_stock if _footprint_matches(c.package, footprint)
    ]

    if footprint_matched:
        logger.debug(
            f"{len(footprint_matched)} candidates match footprint '{footprint}'"
        )
        candidates_to_rank = footprint_matched
    else:
        logger.debug(
            f"No footprint matches found, using all {len(in_stock)} in-stock candidates"
        )
        candidates_to_rank = in_stock

    # Step 3: Score and rank candidates
    scored = [(c, _score_candidate(c, footprint)) for c in candidates_to_rank]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Step 4: Select the top candidate
    selected, score = scored[0]

    logger.info(
        f"Selected {selected.lcsc_part} for {comment} "
        f"(score: {score:.1f}, stock: {selected.stock}, source: {selected.source})"
    )

    return selected, None
