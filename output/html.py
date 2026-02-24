"""HTML report generator for the Stock Sentiment Engine.

Renders a self-contained HTML report using Jinja2 and templates/report.html.
The output file requires no external resources (all CSS is inline), so it
opens correctly in any browser without a web server.

Automatically opens the generated file in the default system browser.
"""

from __future__ import annotations

import logging
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from config import ROOT_DIR

logger = logging.getLogger(__name__)

_TEMPLATE_DIR: Path = ROOT_DIR / "templates"
_TEMPLATE_NAME: str = "report.html"
_DISCLAIMER: str = (
    "This is a research tool, not financial advice. "
    "Always do your own due diligence before making investment decisions."
)


def render(
    analysis: dict[str, Any],
    price_data: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Render and save a self-contained HTML report.

    Args:
        analysis: Parsed dict from analysis.llm.analyze.
        price_data: Output dict from fetchers.price.fetch_price.
        output_dir: Directory where the HTML file will be saved.

    Returns:
        Path to the saved HTML file.
    """
    ticker = price_data.get("symbol") or "UNKNOWN"
    today = date.today().strftime("%Y-%m-%d")
    output_path = Path(output_dir) / f"{ticker}_{today}.html"

    context = _build_context(analysis, price_data, today)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template(_TEMPLATE_NAME)
    html = template.render(**context)

    output_path.write_text(html, encoding="utf-8")
    logger.info(f"[html] Report saved: {output_path}")

    try:
        webbrowser.open(output_path.as_uri())
        logger.debug(f"[html] Opened in browser: {output_path.as_uri()}")
    except Exception as exc:
        logger.debug(f"[html] Could not auto-open browser: {exc}")

    return output_path


# ─── Context Builder ──────────────────────────────────────────────────────────


def _build_context(
    analysis: dict[str, Any],
    price_data: dict[str, Any],
    today: str,
) -> dict[str, Any]:
    """Build the Jinja2 template context from raw analysis and price data."""
    currency = price_data.get("currency") or "USD"
    cur = "C$" if currency == "CAD" else "$"

    # Price snapshot
    current = price_data.get("current_price")
    change_d = price_data.get("day_change_dollars")
    change_p = price_data.get("day_change_percent")
    lo52 = price_data.get("week_52_low")
    hi52 = price_data.get("week_52_high")

    price_str = f"{cur}{current:,.2f}" if current is not None else "N/A"
    change_class = "positive" if (change_p or 0) >= 0 else "negative"
    change_str = _fmt_change(change_d, change_p, cur)
    range_str = (
        f"{cur}{lo52:,.2f} — {cur}{hi52:,.2f}"
        if lo52 is not None and hi52 is not None
        else "N/A"
    )

    # Sentiment scores
    overall = analysis.get("overall_sentiment") or {}
    news_s = analysis.get("news_sentiment") or {}
    reddit_s = analysis.get("reddit_sentiment") or {}
    o_score = float(overall.get("score") or 0)
    n_score = float(news_s.get("score") or 0)
    r_score = float(reddit_s.get("score") or 0)

    # OHLCV table — last 10 bars only
    bars: list[dict[str, Any]] = price_data.get("ohlcv_30days") or []
    n_bars = len(bars)
    ohlcv_rows = []
    for i in range(max(0, n_bars - 10), n_bars):
        b = bars[i]
        ohlcv_rows.append({
            "date":   b.get("date", ""),
            "open":   f"{b.get('open',  0):.2f}",
            "high":   f"{b.get('high',  0):.2f}",
            "low":    f"{b.get('low',   0):.2f}",
            "close":  f"{b.get('close', 0):.2f}",
            "volume": f"{int(b.get('volume', 0)):,}",
        })

    # Earnings
    earnings = analysis.get("earnings") or {}
    beat_or_miss = earnings.get("beat_or_miss") or "N/A"
    beat_class = {"Beat": "positive", "Miss": "negative", "In-line": "neutral"}.get(
        beat_or_miss, "muted"
    )

    # SEC
    sec = analysis.get("sec_filings") or {}

    # Data quality
    dq = analysis.get("data_quality") or {}

    pe = price_data.get("pe_trailing")
    beta = price_data.get("beta")

    # parse_error fallback
    parse_error = bool(analysis.get("_parse_error"))
    raw_response = analysis.get("raw_response", "") if parse_error else ""

    return {
        # Header
        "ticker":         price_data.get("symbol") or "N/A",
        "company_name":   price_data.get("company_name") or "N/A",
        "sector":         price_data.get("sector") or "N/A",
        "industry":       price_data.get("industry") or "N/A",
        "currency":       currency,
        "date":           today,
        # Price
        "price_str":      price_str,
        "change_str":     change_str,
        "change_class":   change_class,
        "range_str":      range_str,
        "mcap_str":       _fmt_large(price_data.get("market_cap"), cur),
        "pe_str":         f"{pe:.1f}x" if pe is not None else "N/A",
        "vol_str":        _fmt_volume(price_data.get("volume_10day_avg")),
        "beta_str":       f"{beta:.2f}" if beta is not None else "N/A",
        "ohlcv_rows":     ohlcv_rows,
        # Sentiment
        "overall_score":      o_score,
        "overall_label":      overall.get("label") or "N/A",
        "overall_confidence": int((overall.get("confidence") or 0) * 100),
        "overall_pct":        _score_to_pct(o_score),
        "overall_colour":     _score_to_css_colour(o_score),
        "news_score":         n_score,
        "news_pct":           _score_to_pct(n_score),
        "news_colour":        _score_to_css_colour(n_score),
        "reddit_score":       r_score,
        "reddit_pct":         _score_to_pct(r_score),
        "reddit_colour":      _score_to_css_colour(r_score),
        # Bull / Bear
        "bull_case":      analysis.get("bull_case") or [],
        "bear_case":      analysis.get("bear_case") or [],
        # News
        "news_summary":   news_s.get("summary") or "",
        "key_articles":   news_s.get("key_articles") or [],
        "news_count":     dq.get("news_count", 0),
        # Reddit
        "reddit_summary": reddit_s.get("summary") or "",
        "notable_posts":  reddit_s.get("notable_posts") or [],
        "reddit_mood":    reddit_s.get("mood") or "N/A",
        "reddit_count":   dq.get("reddit_count", 0),
        # SEC
        "sec_summary":    sec.get("summary") or "",
        "red_flags":      sec.get("red_flags") or [],
        "filing_count":   dq.get("filing_count", 0),
        # Earnings
        "earnings_summary":  earnings.get("summary") or "",
        "beat_or_miss":      beat_or_miss,
        "beat_class":        beat_class,
        "days_until_next":   earnings.get("days_until_next"),
        # Other sections
        "discrepancies":      analysis.get("discrepancies") or [],
        "key_signals":        analysis.get("key_signals") or [],
        "technical_snapshot": analysis.get("technical_snapshot") or "",
        "verdict":            analysis.get("verdict") or "",
        # Data quality
        "data_gaps":       dq.get("data_gaps") or [],
        "confidence_note": dq.get("confidence_note") or "",
        # Misc
        "disclaimer":    _DISCLAIMER,
        "parse_error":   parse_error,
        "raw_response":  raw_response,
    }


# ─── Formatting Helpers ───────────────────────────────────────────────────────


def _score_to_pct(score: float) -> int:
    """Convert a sentiment score [-1, 1] to a gauge fill percentage [0, 100]."""
    return int((score + 1.0) / 2.0 * 100)


def _score_to_css_colour(score: float) -> str:
    """Map a sentiment score to a CSS colour variable name."""
    if score >= 0.1:
        return "var(--positive)"
    if score <= -0.1:
        return "var(--negative)"
    return "var(--neutral)"


def _fmt_change(
    dollars: float | None,
    pct: float | None,
    cur: str,
) -> str:
    """Format a price change as '$X.XX / +X.XX%'."""
    if dollars is None and pct is None:
        return "N/A"
    parts = []
    if dollars is not None:
        sign = "+" if dollars >= 0 else ""
        parts.append(f"{sign}{cur}{abs(dollars):,.2f}")
    if pct is not None:
        sign = "+" if pct >= 0 else ""
        parts.append(f"{sign}{pct:.2f}%")
    return " / ".join(parts)


def _fmt_large(value: int | float | None, prefix: str) -> str:
    """Format a large number with T/B/M suffix."""
    if value is None:
        return "N/A"
    if value >= 1_000_000_000_000:
        return f"{prefix}{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.2f}M"
    return f"{prefix}{value:,.0f}"


def _fmt_volume(value: int | float | None) -> str:
    """Format a volume number with M/K suffix."""
    if value is None:
        return "N/A"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(int(value))
