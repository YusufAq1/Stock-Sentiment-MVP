"""Formats raw fetcher data into a structured XML-style LLM context bundle.

Takes the output dicts from all five fetchers and assembles them into a
single text string that becomes the user message sent to Claude. The
structure uses XML-style tags so Claude can clearly parse each data source.

If the total bundle would exceed the token budget (~80,000 tokens), older
news articles and lower-scored Reddit posts are trimmed first, preserving
the most recent and highest-signal content.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Rough chars-per-token estimate for budget calculations (BPE avg ~4 chars/token).
# _MAX_CHARS mirrors MAX_CONTEXT_TOKENS (80_000) from config.py × 4 chars/token.
_CHARS_PER_TOKEN: int = 4
_MAX_CHARS: int = 80_000 * _CHARS_PER_TOKEN  # ~320,000 chars


def format_context(
    price_data: dict[str, Any],
    news_data: dict[str, Any],
    reddit_data: dict[str, Any],
    sec_data: dict[str, Any],
    earnings_data: dict[str, Any],
) -> str:
    """Build the full LLM context bundle from all fetcher outputs.

    Assembles six XML-tagged sections (ticker_info, price_data,
    news_articles, reddit_posts, sec_filings, earnings) and applies
    truncation if the total length exceeds the token budget.

    Args:
        price_data: Output from fetchers.price.fetch_price.
        news_data: Output from fetchers.news.fetch_news.
        reddit_data: Output from fetchers.reddit.fetch_reddit.
        sec_data: Output from fetchers.sec.fetch_sec.
        earnings_data: Output from fetchers.earnings.fetch_earnings.

    Returns:
        A single string ready to be used as the user message to Claude.
    """
    currency = price_data.get("currency") or "USD"

    # Build each section independently
    ticker_section = _build_ticker_info(price_data, currency)
    price_section = _build_price_data(price_data, currency)
    earnings_section = _build_earnings(earnings_data)
    sec_section = _build_sec_filings(sec_data)

    # News and Reddit may be trimmed — work with mutable copies
    articles = list(news_data.get("articles") or [])
    posts = list(reddit_data.get("posts") or [])
    stats = reddit_data.get("stats") or {}

    # Estimate budget consumed by fixed sections
    fixed = "\n\n".join([ticker_section, price_section, earnings_section, sec_section])
    remaining_budget = _MAX_CHARS - len(fixed)

    # Trim news and Reddit to fit, tracking how many items were cut
    articles, news_trimmed = _trim_articles(articles, remaining_budget // 2)
    posts, reddit_trimmed = _trim_posts(posts, remaining_budget // 2)

    news_section = _build_news_articles(articles, news_trimmed)
    reddit_section = _build_reddit_posts(posts, stats, reddit_trimmed)

    bundle = "\n\n".join(
        [
            ticker_section,
            price_section,
            news_section,
            reddit_section,
            sec_section,
            earnings_section,
        ]
    )

    total_tokens_est = len(bundle) // _CHARS_PER_TOKEN
    logger.debug(f"[formatter] Bundle: ~{total_tokens_est:,} tokens ({len(bundle):,} chars)")

    if news_trimmed or reddit_trimmed:
        logger.info(
            f"[formatter] Trimmed {news_trimmed} news articles and "
            f"{reddit_trimmed} Reddit posts to fit token budget"
        )

    return bundle


# ─── Section Builders ─────────────────────────────────────────────────────────


def _build_ticker_info(price: dict[str, Any], currency: str) -> str:
    """Build the <ticker_info> section with key company and price stats."""
    sym = price.get("symbol") or "N/A"
    name = price.get("company_name") or "N/A"
    sector = price.get("sector") or "N/A"
    industry = price.get("industry") or "N/A"

    current = price.get("current_price")
    change_d = price.get("day_change_dollars")
    change_p = price.get("day_change_percent")
    prev = price.get("previous_close")
    hi52 = price.get("week_52_high")
    lo52 = price.get("week_52_low")
    mcap = price.get("market_cap")
    vol10 = price.get("volume_10day_avg")
    vol3m = price.get("volume_3month_avg")
    pe_t = price.get("pe_trailing")
    pe_f = price.get("pe_forward")
    eps = price.get("eps_trailing")
    div = price.get("dividend_yield")
    beta = price.get("beta")

    lines = [
        f"<ticker_info>",
        f"Symbol: {sym}",
        f"Company: {name}",
        f"Sector: {sector}",
        f"Industry: {industry}",
        f"Currency: {currency}",
        f"Current Price: {_fmt_price(current, currency)} "
        f"({_fmt_change(change_d, change_p)})",
        f"Previous Close: {_fmt_price(prev, currency)}",
        f"52-Week Range: {_fmt_price(lo52, currency)} — {_fmt_price(hi52, currency)}",
        f"Market Cap: {_fmt_large(mcap, currency)}",
        f"Avg Volume (10d): {_fmt_volume(vol10)}",
        f"Avg Volume (3m): {_fmt_volume(vol3m)}",
        f"Trailing P/E: {_fmt_float(pe_t, 2)}",
        f"Forward P/E: {_fmt_float(pe_f, 2)}",
        f"EPS (TTM): {_fmt_float(eps, 2)}",
        f"Dividend Yield: {_fmt_pct(div)}",
        f"Beta: {_fmt_float(beta, 2)}",
        f"</ticker_info>",
    ]
    return "\n".join(lines)


def _build_price_data(price: dict[str, Any], currency: str) -> str:
    """Build the <price_data> section with OHLCV summary and trend notes."""
    bars: list[dict[str, Any]] = price.get("ohlcv_30days") or []

    if not bars:
        return "<price_data>\nNo OHLCV data available.\n</price_data>"

    first = bars[0]
    last = bars[-1]
    period_start = first.get("date", "N/A")
    period_end = last.get("date", "N/A")

    highs: list[float] = [b["high"] for b in bars if b.get("high") is not None]
    lows: list[float] = [b["low"] for b in bars if b.get("low") is not None]
    closes: list[float] = [b["close"] for b in bars if b.get("close") is not None]
    volumes: list[int] = [b["volume"] for b in bars if b.get("volume") is not None]

    period_high = max(highs) if highs else None
    period_low = min(lows) if lows else None
    open_price = first.get("open")
    close_price = last.get("close")
    avg_volume = int(sum(volumes) / len(volumes)) if volumes else None

    # Trend: compare most recent 5 closes vs prior 5 closes
    trend_note = ""
    if len(closes) >= 10:
        n = len(closes)
        recent_avg = sum(closes[i] for i in range(n - 5, n)) / 5
        prior_avg = sum(closes[i] for i in range(n - 10, n - 5)) / 5
        if recent_avg > prior_avg * 1.02:
            trend_note = "Recent trend: Upward (last 5 days avg above prior 5 days)."
        elif recent_avg < prior_avg * 0.98:
            trend_note = "Recent trend: Downward (last 5 days avg below prior 5 days)."
        else:
            trend_note = "Recent trend: Sideways (last 5 days avg near prior 5 days)."

    # Overall period change
    period_change = ""
    if open_price and close_price and open_price != 0:
        chg = ((close_price - open_price) / open_price) * 100
        sign = "+" if chg >= 0 else ""
        period_change = f"Period change: {sign}{chg:.2f}% ({_fmt_price(open_price, currency)} → {_fmt_price(close_price, currency)})."

    # Recent OHLCV table (last 10 bars)
    table_lines = ["Date         Open      High      Low       Close     Volume"]
    n_bars = len(bars)
    for i in range(max(0, n_bars - 10), n_bars):
        bar = bars[i]
        table_lines.append(
            f"{bar.get('date',''):12s} "
            f"{bar.get('open',0):>9.2f} "
            f"{bar.get('high',0):>9.2f} "
            f"{bar.get('low',0):>9.2f} "
            f"{bar.get('close',0):>9.2f} "
            f"{bar.get('volume',0):>12,}"
        )
    table = "\n".join(table_lines)

    lines = [
        "<price_data>",
        f"Period: {period_start} to {period_end} ({len(bars)} trading days)",
        period_change,
        f"Period High: {_fmt_price(period_high, currency)}  |  Period Low: {_fmt_price(period_low, currency)}",
        f"Average Daily Volume: {_fmt_volume(avg_volume)}",
        trend_note,
        "",
        "Recent OHLCV (last 10 bars):",
        table,
        "</price_data>",
    ]
    return "\n".join(line for line in lines if line is not None)


def _build_news_articles(
    articles: list[dict[str, Any]],
    trimmed_count: int,
) -> str:
    """Build the <news_articles> section."""
    count = len(articles)
    note = f' trimmed="{trimmed_count}"' if trimmed_count else ""
    lines = [f'<news_articles count="{count}"{note}>']

    if not articles:
        lines.append("No news articles found for this period.")
    else:
        for article in articles:
            source = _escape(article.get("source") or "Unknown")
            date = (article.get("published_at") or "")[:10]
            title = _escape(article.get("title") or "")
            summary = _escape(article.get("summary") or "")
            provider = article.get("provider", "")

            lines.append(f'<article source="{source}" date="{date}" provider="{provider}">')
            lines.append(f"Headline: {title}")
            if summary:
                lines.append(f"Summary: {summary}")
            lines.append("</article>")

    lines.append("</news_articles>")
    return "\n".join(lines)


def _build_reddit_posts(
    posts: list[dict[str, Any]],
    stats: dict[str, Any],
    trimmed_count: int,
) -> str:
    """Build the <reddit_posts> section with summary stats and individual posts."""
    count = len(posts)
    total_posts = stats.get("total_posts", count)
    breakdown = stats.get("subreddit_breakdown") or {}
    subreddits_str = ",".join(sorted(breakdown.keys())) if breakdown else "N/A"
    note = f' trimmed="{trimmed_count}"' if trimmed_count else ""

    lines = [f'<reddit_posts count="{count}" subreddits="{subreddits_str}"{note}>']

    # Summary block
    avg_score = stats.get("avg_score", 0)
    total_comments = stats.get("total_comments", 0)
    most_active = "N/A"
    most_active_count = 0
    if breakdown:
        for _sub, _cnt in breakdown.items():
            if _cnt > most_active_count:
                most_active_count = _cnt
                most_active = _sub

    lines += [
        "<summary>",
        f"Total posts found: {total_posts}",
        f"Posts included: {count}",
        f"Average post score: {avg_score}",
        f"Total comments: {total_comments}",
        f"Most active subreddit: {most_active} ({most_active_count} posts)",
        "</summary>",
    ]

    if not posts:
        lines.append("No Reddit posts found for this ticker.")
    else:
        for post in posts:
            subreddit = _escape(post.get("subreddit") or "")
            score = post.get("score", 0)
            num_comments = post.get("num_comments", 0)
            created = post.get("created_utc")
            date_str = _unix_to_date(created)
            title = _escape(post.get("title") or "")
            body = _escape((post.get("body") or "").strip())
            top_comments: list[dict[str, Any]] = post.get("top_comments") or []

            lines.append(
                f'<post subreddit="{subreddit}" score="{score}" '
                f'comments="{num_comments}" date="{date_str}">'
            )
            lines.append(f"Title: {title}")
            if body:
                # Truncate very long post bodies to keep context manageable
                if len(body) > 500:
                    body_preview = "".join(body[j] for j in range(500)) + "..."
                else:
                    body_preview = body
                lines.append(f"Body: {body_preview}")
            if top_comments:
                lines.append("Top comments:")
                for c in top_comments:
                    c_body = _escape((c.get("body") or "").strip())
                    c_score = c.get("score", 0)
                    if c_body:
                        c_preview = "".join(c_body[j] for j in range(min(len(c_body), 200)))
                        lines.append(f"  [{c_score}] {c_preview}")
            lines.append("</post>")

    lines.append("</reddit_posts>")
    return "\n".join(lines)


def _build_sec_filings(sec: dict[str, Any]) -> str:
    """Build the <sec_filings> section."""
    filings: list[dict[str, Any]] = sec.get("filings") or []
    is_us = sec.get("is_us_listed", True)
    note = sec.get("note") or ""
    count = len(filings)

    lines = [f'<sec_filings count="{count}">']

    if not is_us:
        lines.append(note or "No SEC filings (non-US listed security).")
    elif not filings:
        lines.append(note or "No recent SEC filings found.")
    else:
        if note:
            lines.append(f"Note: {note}")
        for filing in filings:
            form_type = _escape(filing.get("form_type") or "")
            date = filing.get("filing_date") or ""
            description = _escape(filing.get("description") or "")
            url = filing.get("url") or ""
            content = filing.get("content")

            lines.append(f'<filing type="{form_type}" date="{date}">')
            if description:
                lines.append(f"Description: {description}")
            lines.append(f"URL: {url}")
            if content:
                lines.append(f"Content: {content}")
            lines.append("</filing>")

    lines.append("</sec_filings>")
    return "\n".join(lines)


def _build_earnings(earnings: dict[str, Any]) -> str:
    """Build the <earnings> section."""
    next_date = earnings.get("next_earnings_date")
    days_until = earnings.get("days_until_next")
    lq: dict[str, Any] = earnings.get("last_quarter") or {}

    next_str = "Unknown"
    if next_date:
        try:
            dt = datetime.strptime(next_date, "%Y-%m-%d")
            # %d gives zero-padded day; lstrip removes the leading zero on single-digit days
            next_str = f"{dt.strftime('%B')} {dt.day}, {dt.strftime('%Y')}"
        except ValueError:
            next_str = next_date
        if days_until is not None:
            next_str += f" ({days_until} days away)"

    beat_or_miss = lq.get("beat_or_miss") or "N/A"
    eps_est = lq.get("eps_estimate")
    eps_act = lq.get("eps_actual")
    surprise = lq.get("eps_surprise_pct")
    period = lq.get("period") or "N/A"

    last_q_parts = [f"Result: {beat_or_miss}"]
    if eps_est is not None and eps_act is not None:
        last_q_parts.append(
            f"EPS estimate {_fmt_float(eps_est, 2)} vs actual {_fmt_float(eps_act, 2)}"
        )
    if surprise is not None:
        sign = "+" if surprise >= 0 else ""
        last_q_parts.append(f"EPS surprise: {sign}{surprise:.2f}%")

    lines = [
        "<earnings>",
        f"Next earnings date: {next_str}",
        f"Most recent quarter ({period}): {', '.join(last_q_parts)}",
        "</earnings>",
    ]
    return "\n".join(lines)


# ─── Truncation Helpers ───────────────────────────────────────────────────────


def _trim_articles(
    articles: list[dict[str, Any]],
    budget: int,
) -> tuple[list[dict[str, Any]], int]:
    """Trim news articles to fit within the character budget.

    Articles are already sorted newest-first. Oldest articles (at the end
    of the list) are removed first to preserve the most recent content.

    Args:
        articles: List of article dicts, sorted newest-first.
        budget: Maximum character budget for all articles combined.

    Returns:
        Tuple of (trimmed_articles, number_removed).
    """
    serialised = _estimate_articles_size(articles)
    if serialised <= budget:
        return articles, 0

    removed = 0
    while articles and _estimate_articles_size(articles) > budget:
        articles.pop()  # remove oldest (last in list)
        removed += 1

    return articles, removed


def _trim_posts(
    posts: list[dict[str, Any]],
    budget: int,
) -> tuple[list[dict[str, Any]], int]:
    """Trim Reddit posts to fit within the character budget.

    Posts are already sorted by score descending. Lowest-scored posts
    (at the end of the list) are removed first.

    Args:
        posts: List of post dicts, sorted by score descending.
        budget: Maximum character budget for all posts combined.

    Returns:
        Tuple of (trimmed_posts, number_removed).
    """
    serialised = _estimate_posts_size(posts)
    if serialised <= budget:
        return posts, 0

    removed = 0
    while posts and _estimate_posts_size(posts) > budget:
        posts.pop()  # remove lowest-scored (last in list)
        removed += 1

    return posts, removed


def _estimate_articles_size(articles: list[dict[str, Any]]) -> int:
    """Rough character count for a list of articles."""
    total = 0
    for a in articles:
        total += len(a.get("title") or "") + len(a.get("summary") or "") + 80
    return total


def _estimate_posts_size(posts: list[dict[str, Any]]) -> int:
    """Rough character count for a list of posts."""
    total = 0
    for p in posts:
        total += len(p.get("title") or "") + min(len(p.get("body") or ""), 500) + 150
        for c in (p.get("top_comments") or []):
            total += min(len(c.get("body") or ""), 200) + 20
    return total


# ─── Formatting Helpers ───────────────────────────────────────────────────────


def _fmt_price(value: float | None, currency: str) -> str:
    """Format a price with the correct currency prefix."""
    if value is None:
        return "N/A"
    prefix = "C$" if currency == "CAD" else "$"
    return f"{prefix}{value:,.2f}"


def _fmt_change(dollars: float | None, pct: float | None) -> str:
    """Format a price change as '$X.XX / +X.XX%'."""
    if dollars is None and pct is None:
        return "N/A"
    parts = []
    if dollars is not None:
        sign = "+" if dollars >= 0 else ""
        parts.append(f"{sign}{dollars:,.2f}")
    if pct is not None:
        sign = "+" if pct >= 0 else ""
        parts.append(f"{sign}{pct:.2f}%")
    return " / ".join(parts)


def _fmt_large(value: int | None, currency: str) -> str:
    """Format a large number (e.g. market cap) with B/M suffix."""
    if value is None:
        return "N/A"
    prefix = "C$" if currency == "CAD" else "$"
    if value >= 1_000_000_000_000:
        return f"{prefix}{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.2f}M"
    return f"{prefix}{value:,}"


def _fmt_volume(value: int | None) -> str:
    """Format a volume number with M/K suffix."""
    if value is None:
        return "N/A"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _fmt_float(value: float | None, decimals: int = 2) -> str:
    """Format a float to a fixed number of decimal places."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def _fmt_pct(value: float | None) -> str:
    """Format a decimal fraction as a percentage (e.g. 0.0044 → '0.44%')."""
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _escape(text: str) -> str:
    """Minimally escape text for embedding in XML-style tags."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _unix_to_date(timestamp: Any) -> str:
    """Convert a Unix timestamp to a 'YYYY-MM-DD' date string."""
    if timestamp is None:
        return "N/A"
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
    except (ValueError, OSError, OverflowError):
        return "N/A"
