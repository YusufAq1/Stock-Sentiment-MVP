"""Rich terminal output for the Stock Sentiment Engine.

Renders the parsed LLM analysis and supporting price data as a
formatted, colour-coded terminal report using the `rich` library.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)

# Sentiment score → (colour, label) thresholds
_SENTIMENT_THRESHOLDS: list[tuple[float, str, str]] = [
    (0.5,  "bright_green",  "Very Bullish"),
    (0.3,  "green",         "Bullish"),
    (0.1,  "green",         "Slightly Bullish"),
    (-0.1, "yellow",        "Neutral"),
    (-0.3, "red",           "Slightly Bearish"),
    (-0.5, "red",           "Bearish"),
]
_DEFAULT_SENTIMENT = ("bright_red", "Very Bearish")

_BAR_WIDTH: int = 10   # total █/░ characters in gauge bars
_DISCLAIMER: str = (
    "This is a research tool, not financial advice. "
    "Always do your own due diligence before making investment decisions."
)


def render(
    analysis: dict[str, Any],
    price_data: dict[str, Any],
    console: Console | None = None,
) -> None:
    """Render the full analysis report to the terminal.

    Args:
        analysis: Parsed dict from analysis.llm.analyze.
        price_data: Output dict from fetchers.price.fetch_price.
        console: Optional rich Console instance. Creates a default one
            if not provided.
    """
    if console is None:
        console = Console()

    ticker = price_data.get("symbol") or "N/A"
    company = price_data.get("company_name") or "N/A"
    today = date.today().strftime("%Y-%m-%d")

    # If LLM returned a parse error fallback, show raw text and exit
    if analysis.get("_parse_error"):
        console.print(
            Panel(
                analysis.get("raw_response", "(empty)"),
                title=f"[bold yellow]{ticker} — Raw LLM Response (parse failed)[/]",
                border_style="yellow",
            )
        )
        return

    console.print()
    console.print(Rule(
        f"[bold white] {ticker} — {company}    {today} [/bold white]",
        style="bright_blue",
    ))

    _render_price_snapshot(console, price_data)
    _render_sentiment_gauges(console, analysis)
    _render_bull_bear(console, analysis)
    _render_news(console, analysis)
    _render_reddit(console, analysis)
    _render_sec(console, analysis)
    _render_earnings(console, analysis)
    _render_discrepancies(console, analysis)
    _render_key_signals(console, analysis)
    _render_technical(console, analysis)
    _render_verdict(console, analysis)
    _render_data_quality(console, analysis)

    console.print(
        Panel(
            f"[dim italic]{_DISCLAIMER}[/]",
            border_style="dim",
            padding=(0, 1),
        )
    )
    console.print()


# ─── Section Renderers ────────────────────────────────────────────────────────


def _render_price_snapshot(console: Console, price: dict[str, Any]) -> None:
    """Render the PRICE SNAPSHOT panel."""
    currency = price.get("currency") or "USD"
    cur = "C$" if currency == "CAD" else "$"

    current = price.get("current_price")
    change_d = price.get("day_change_dollars")
    change_p = price.get("day_change_percent")
    hi52 = price.get("week_52_high")
    lo52 = price.get("week_52_low")
    pe_t = price.get("pe_trailing")
    mcap = price.get("market_cap")
    vol = price.get("volume_10day_avg")

    price_str = f"{cur}{current:,.2f}" if current is not None else "N/A"
    change_colour = "green" if (change_p or 0) >= 0 else "red"
    change_str = ""
    if change_d is not None or change_p is not None:
        sign = "+" if (change_p or 0) >= 0 else ""
        d_part = f"{cur}{change_d:+,.2f}" if change_d is not None else ""
        p_part = f"{sign}{change_p:.2f}%" if change_p is not None else ""
        change_str = " / ".join(p for p in [d_part, p_part] if p)

    range_str = (
        f"{cur}{lo52:,.2f} — {cur}{hi52:,.2f}"
        if lo52 is not None and hi52 is not None
        else "N/A"
    )
    pe_str = f"{pe_t:.1f}x" if pe_t is not None else "N/A"
    mcap_str = _fmt_large(mcap, cur)
    vol_str = _fmt_volume(vol)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_column(style="bold")
    table.add_column()

    table.add_row(
        "Price:",
        Text(f"{price_str}  ", style="bold white") + Text(change_str, style=change_colour),
        "52W Range:",
        range_str,
    )
    table.add_row("Market Cap:", mcap_str, "Trailing P/E:", pe_str)
    table.add_row("Avg Vol (10d):", vol_str, "", "")

    console.print(Panel(table, title="[bold]PRICE SNAPSHOT[/]", border_style="blue", padding=(0, 1)))


def _render_sentiment_gauges(console: Console, analysis: dict[str, Any]) -> None:
    """Render the colour-coded SENTIMENT GAUGE panel."""
    overall = analysis.get("overall_sentiment") or {}
    news_s = analysis.get("news_sentiment") or {}
    reddit_s = analysis.get("reddit_sentiment") or {}

    o_score = overall.get("score") or 0.0
    o_label = overall.get("label") or "N/A"
    o_conf = overall.get("confidence")
    n_score = news_s.get("score") or 0.0
    r_score = reddit_s.get("score") or 0.0
    r_mood = reddit_s.get("mood") or ""

    conf_str = f"  [dim]Confidence: {o_conf * 100:.0f}%[/]" if o_conf is not None else ""

    rows = [
        ("Overall", o_score, f"{o_label}{conf_str}"),
        ("News", n_score, ""),
        ("Reddit", r_score, f"Mood: {r_mood}" if r_mood else ""),
    ]

    text = Text()
    for label, score, annotation in rows:
        colour, _ = _score_to_colour_label(score)
        bar = _gauge_bar(score, colour)
        score_txt = f"{score:+.2f}"
        text.append(f"  {label:<10}", style="bold")
        text.append_text(bar)
        text.append(f"  {score_txt}  ", style=colour)
        if annotation:
            text.append(annotation, style="dim")
        text.append("\n")

    console.print(Panel(text, title="[bold]SENTIMENT GAUGE[/]", border_style="blue", padding=(0, 1)))


def _render_bull_bear(console: Console, analysis: dict[str, Any]) -> None:
    """Render the bull case and bear case side-by-side."""
    bull = analysis.get("bull_case") or []
    bear = analysis.get("bear_case") or []

    bull_text = Text()
    for point in bull:
        bull_text.append("• ", style="bold green")
        bull_text.append(point + "\n")

    bear_text = Text()
    for point in bear:
        bear_text.append("• ", style="bold red")
        bear_text.append(point + "\n")

    bull_panel = Panel(bull_text, title="[bold green]BULL CASE[/]", border_style="green", padding=(0, 1))
    bear_panel = Panel(bear_text, title="[bold red]BEAR CASE[/]", border_style="red", padding=(0, 1))

    console.print(Columns([bull_panel, bear_panel]))


def _render_news(console: Console, analysis: dict[str, Any]) -> None:
    """Render the NEWS SUMMARY panel."""
    news = analysis.get("news_sentiment") or {}
    summary = news.get("summary") or "No news summary available."
    key_articles = news.get("key_articles") or []
    dq = analysis.get("data_quality") or {}
    count = dq.get("news_count", 0)

    text = Text()
    text.append(summary + "\n")
    if key_articles:
        text.append("\nKey articles:\n", style="bold")
        for article in key_articles:
            text.append("• ", style="dim")
            text.append(article + "\n")

    console.print(Panel(
        text,
        title=f"[bold]NEWS SUMMARY[/bold] [dim]({count} articles)[/dim]",
        border_style="blue",
        padding=(0, 1),
    ))


def _render_reddit(console: Console, analysis: dict[str, Any]) -> None:
    """Render the REDDIT PULSE panel."""
    reddit = analysis.get("reddit_sentiment") or {}
    summary = reddit.get("summary") or "No Reddit data available."
    mood = reddit.get("mood") or "N/A"
    notable = reddit.get("notable_posts") or []
    dq = analysis.get("data_quality") or {}
    count = dq.get("reddit_count", 0)

    text = Text()
    text.append(summary + "\n")
    if notable:
        text.append("\nNotable posts:\n", style="bold")
        for post in notable:
            text.append("• ", style="dim")
            text.append(post + "\n")

    console.print(Panel(
        text,
        title=f"[bold]REDDIT PULSE[/bold] [dim]({count} posts — Mood: {mood})[/dim]",
        border_style="blue",
        padding=(0, 1),
    ))


def _render_sec(console: Console, analysis: dict[str, Any]) -> None:
    """Render the SEC FILINGS panel."""
    sec = analysis.get("sec_filings") or {}
    summary = sec.get("summary") or "No SEC filings data."
    red_flags = sec.get("red_flags") or []
    dq = analysis.get("data_quality") or {}
    count = dq.get("filing_count", 0)

    text = Text()
    text.append(summary + "\n")
    if red_flags:
        text.append("\nRed flags:\n", style="bold red")
        for flag in red_flags:
            text.append("⚠  ", style="red")
            text.append(flag + "\n")

    console.print(Panel(
        text,
        title=f"[bold]SEC FILINGS[/bold] [dim]({count} recent filings)[/dim]",
        border_style="blue",
        padding=(0, 1),
    ))


def _render_earnings(console: Console, analysis: dict[str, Any]) -> None:
    """Render the EARNINGS panel."""
    earnings = analysis.get("earnings") or {}
    summary = earnings.get("summary") or "No earnings data available."
    beat_or_miss = earnings.get("beat_or_miss") or "N/A"
    days_until = earnings.get("days_until_next")

    bom_colour = {"Beat": "green", "Miss": "red", "In-line": "yellow"}.get(beat_or_miss, "dim")
    days_str = f"  [dim]{days_until} days until next earnings[/]" if days_until is not None else ""

    text = Text()
    text.append("Last quarter: ")
    text.append(beat_or_miss, style=f"bold {bom_colour}")
    text.append(days_str + "\n")
    text.append(summary)

    console.print(Panel(text, title="[bold]EARNINGS[/]", border_style="blue", padding=(0, 1)))


def _render_discrepancies(console: Console, analysis: dict[str, Any]) -> None:
    """Render the DISCREPANCIES panel (only if any exist)."""
    items = analysis.get("discrepancies") or []
    if not items:
        return

    text = Text()
    for item in items:
        text.append("⚠  ", style="yellow")
        text.append(item + "\n")

    console.print(Panel(text, title="[bold yellow]DISCREPANCIES[/]", border_style="yellow", padding=(0, 1)))


def _render_key_signals(console: Console, analysis: dict[str, Any]) -> None:
    """Render the KEY SIGNALS panel."""
    signals = analysis.get("key_signals") or []
    if not signals:
        return

    text = Text()
    for signal in signals:
        text.append("▸ ", style="bold cyan")
        text.append(signal + "\n")

    console.print(Panel(text, title="[bold cyan]KEY SIGNALS[/]", border_style="cyan", padding=(0, 1)))


def _render_technical(console: Console, analysis: dict[str, Any]) -> None:
    """Render the TECHNICAL SNAPSHOT panel."""
    snapshot = analysis.get("technical_snapshot") or "No technical data available."
    console.print(Panel(
        Text(snapshot),
        title="[bold]TECHNICAL SNAPSHOT[/]",
        border_style="blue",
        padding=(0, 1),
    ))


def _render_verdict(console: Console, analysis: dict[str, Any]) -> None:
    """Render the VERDICT panel."""
    verdict = analysis.get("verdict") or "No verdict available."
    console.print(Panel(
        Text(verdict),
        title="[bold white]VERDICT[/]",
        border_style="bright_white",
        padding=(0, 1),
    ))


def _render_data_quality(console: Console, analysis: dict[str, Any]) -> None:
    """Render the DATA QUALITY panel if there are notable gaps."""
    dq = analysis.get("data_quality") or {}
    gaps = dq.get("data_gaps") or []
    note = dq.get("confidence_note") or ""

    if not gaps and not note:
        return

    text = Text()
    for gap in gaps:
        text.append("• ", style="dim yellow")
        text.append(gap + "\n", style="dim")
    if note:
        text.append(note, style="dim italic")

    console.print(Panel(text, title="[dim]DATA QUALITY[/]", border_style="dim", padding=(0, 1)))


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _score_to_colour_label(score: float) -> tuple[str, str]:
    """Map a sentiment score (-1.0 to 1.0) to a (colour, label) pair."""
    for threshold, colour, label in _SENTIMENT_THRESHOLDS:
        if score >= threshold:
            return colour, label
    return _DEFAULT_SENTIMENT


def _gauge_bar(score: float, colour: str) -> Text:
    """Build a visual █/░ gauge bar for a sentiment score.

    Args:
        score: Sentiment score in [-1.0, 1.0].
        colour: Rich colour name for filled blocks.

    Returns:
        A rich Text object containing the bar.
    """
    # Map score from [-1, 1] to [0, BAR_WIDTH]
    filled = round((score + 1.0) / 2.0 * _BAR_WIDTH)
    filled = max(0, min(_BAR_WIDTH, filled))

    bar = Text()
    bar.append("█" * filled, style=colour)
    bar.append("░" * (_BAR_WIDTH - filled), style="dim")
    return bar


def _fmt_large(value: int | float | None, prefix: str) -> str:
    """Format a large number (e.g. market cap) with B/M/T suffix."""
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
