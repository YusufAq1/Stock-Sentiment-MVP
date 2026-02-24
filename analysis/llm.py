"""LLM analysis module — sends the formatted context bundle to Claude.

Makes a single Anthropic API call with a detailed system prompt and the
formatted data bundle as the user message. Parses the JSON response and
returns a structured analysis dict.

Retry logic uses exponential backoff (1s, 2s, 4s) for API errors.
If JSON parsing fails after all retries, falls back to returning the raw
text so the pipeline can still render partial output.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import anthropic

from config import (
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_RETRY_BASE_SECONDS,
)

logger = logging.getLogger(__name__)

# ─── System Prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT: str = """You are a senior equity research analyst producing a comprehensive research brief for a stock ticker. You have been given real-time data including news articles, Reddit discussions, SEC filings, earnings data, and price action.

Your job is to synthesize ALL of this data into an actionable research brief. Be specific — cite particular articles, Reddit posts, or filings when making claims. Do not be generic.

You must respond with a JSON object matching this exact schema:

{
  "overall_sentiment": {
    "score": <float from -1.0 (very bearish) to 1.0 (very bullish)>,
    "label": <"Very Bearish" | "Bearish" | "Slightly Bearish" | "Neutral" | "Slightly Bullish" | "Bullish" | "Very Bullish">,
    "confidence": <float from 0.0 to 1.0 — how confident you are in this assessment given the available data>
  },
  "news_sentiment": {
    "score": <float -1.0 to 1.0>,
    "summary": <string — 3-5 sentence summary of the key themes from news coverage>,
    "key_articles": [<list of 3-5 strings, each a one-sentence summary of the most impactful articles>]
  },
  "reddit_sentiment": {
    "score": <float -1.0 to 1.0>,
    "mood": <"FOMO" | "Fear" | "Euphoria" | "Anxiety" | "Indifferent" | "Divided" | "Cautiously Optimistic" | "Cautiously Pessimistic">,
    "summary": <string — 2-3 sentence summary of what retail traders are saying>,
    "notable_posts": [<list of 2-3 strings, each summarizing a notable Reddit post or viewpoint>]
  },
  "sec_filings": {
    "has_recent_filings": <boolean>,
    "summary": <string — summary of any notable recent filings, or "No recent SEC filings" / "Not applicable (non-US listed)">,
    "red_flags": [<list of strings — any concerning items from filings, empty list if none>]
  },
  "earnings": {
    "summary": <string — earnings context: recent performance, next date, expectations>,
    "beat_or_miss": <"Beat" | "Miss" | "In-line" | "N/A">,
    "days_until_next": <int or null>
  },
  "bull_case": [<list of 3-5 strings — the strongest bullish arguments based on the data>],
  "bear_case": [<list of 3-5 strings — the strongest bearish arguments based on the data>],
  "discrepancies": [<list of strings — any notable divergences: news vs reddit sentiment, price vs sentiment, insider actions vs public narrative, etc. Empty list if none>],
  "key_signals": [<list of strings — upcoming catalysts, events, dates, or patterns to watch>],
  "technical_snapshot": <string — brief technical analysis based on the price data: trend direction, support/resistance, volume patterns, notable moving average positions>,
  "verdict": <string — 3-5 sentence plain-English verdict summarizing the overall picture and what an investor should pay attention to. Do NOT give buy/sell advice. Frame as "here's what the data suggests" and "here's what to watch for.">,
  "data_quality": {
    "news_count": <int — number of articles analyzed>,
    "reddit_count": <int — number of Reddit posts analyzed>,
    "filing_count": <int — number of SEC filings found>,
    "data_gaps": [<list of strings — any notable gaps: "Low news coverage", "No SEC filings", "Limited Reddit discussion", etc.>],
    "confidence_note": <string — if data is sparse, explain how that affects confidence>
  }
}

Important rules:
- Be SPECIFIC. Reference actual articles, posts, and data points. Don't be vague.
- Be HONEST about uncertainty. If data is sparse (especially for TSX/Canadian stocks), say so and lower your confidence.
- Do NOT give financial advice. Do not say "buy" or "sell". Frame everything as analysis, not recommendation.
- If news and Reddit sentiment disagree, call it out explicitly in discrepancies.
- If price action contradicts sentiment (e.g., price rising but sentiment is bearish), flag it.
- Consider recency — weight very recent information more heavily.
- For the verdict, be direct and opinionated about what the data shows, but always note caveats."""


def analyze(
    context_bundle: str,
    anthropic_api_key: str,
) -> dict[str, Any]:
    """Send the context bundle to Claude and return the parsed analysis.

    Makes up to LLM_MAX_RETRIES attempts with exponential backoff. On each
    attempt, sends the full context bundle as the user message. Parses the
    JSON from Claude's response; if parsing fails after all retries, returns
    a fallback dict containing the raw text.

    Args:
        context_bundle: The formatted data string from analysis.formatter.
        anthropic_api_key: Anthropic API key for authentication.

    Returns:
        Parsed analysis dict matching the schema in the system prompt, or
        a fallback dict with a "raw_response" key if parsing failed.

    Raises:
        SystemExit: With exit code 4 if all retries are exhausted due to
            unrecoverable API errors (non-rate-limit errors).
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    last_exc: Exception | None = None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            logger.info(
                f"[llm] Sending context bundle to Claude "
                f"(attempt {attempt}/{LLM_MAX_RETRIES}, "
                f"~{len(context_bundle):,} chars)"
            )

            message = client.messages.create(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context_bundle}],
            )

            raw_text = message.content[0].text
            logger.debug(f"[llm] Raw response length: {len(raw_text):,} chars")

            parsed = _parse_json_response(raw_text)
            if parsed is not None:
                logger.info("[llm] Analysis complete — JSON parsed successfully")
                return parsed

            # JSON parse failed — log and retry (or fall through on last attempt)
            logger.warning(
                f"[llm] JSON parsing failed on attempt {attempt} — "
                "response may be malformed"
            )
            if attempt == LLM_MAX_RETRIES:
                logger.error("[llm] All retries exhausted; returning raw text fallback")
                return {"raw_response": raw_text, "_parse_error": True}

        except anthropic.RateLimitError as exc:
            last_exc = exc
            wait = LLM_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                f"[llm] Rate limited (attempt {attempt}); retrying in {wait:.0f}s"
            )
            time.sleep(wait)

        except anthropic.APIStatusError as exc:
            last_exc = exc
            # 5xx server errors are retryable; 4xx (except 429) are not
            if exc.status_code >= 500:
                wait = LLM_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"[llm] Server error {exc.status_code} (attempt {attempt}); "
                    f"retrying in {wait:.0f}s"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"[llm] Non-retryable API error {exc.status_code}: {exc.message}"
                )
                raise SystemExit(4) from exc

        except anthropic.APIConnectionError as exc:
            last_exc = exc
            wait = LLM_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                f"[llm] Connection error (attempt {attempt}); retrying in {wait:.0f}s"
            )
            time.sleep(wait)

    # All retries exhausted due to persistent API errors
    logger.error(f"[llm] All {LLM_MAX_RETRIES} retries failed: {last_exc}")
    raise SystemExit(4) from last_exc


def _parse_json_response(text: str) -> dict[str, Any] | None:
    """Extract and parse a JSON object from Claude's response text.

    Claude sometimes wraps the JSON in a markdown code block. This
    function strips fences before parsing.

    Args:
        text: Raw text response from Claude.

    Returns:
        Parsed dict, or None if no valid JSON could be extracted.
    """
    # Strip ```json ... ``` or ``` ... ``` fences if present
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find a top-level JSON object if the text has preamble
    if not text.startswith("{"):
        brace_start = text.find("{")
        if brace_start != -1:
            text = text[brace_start:]

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        logger.warning("[llm] Parsed JSON is not a dict — unexpected shape")
        return None
    except json.JSONDecodeError as exc:
        logger.debug(f"[llm] JSON decode error: {exc}")
        return None
