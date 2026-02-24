"""Stock Sentiment Engine — CLI entry point.

Aggregates financial news, Reddit posts, SEC filings, earnings data, and
price action for a given ticker, then uses Claude to produce a research brief.

Usage:
    python analyze.py AAPL
    python analyze.py SHOP.TO --no-cache
    python analyze.py AAPL --days 7 --verbose
    python analyze.py AAPL --terminal-only
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from config import (
    CACHE_DIR,
    DEFAULT_DAYS,
    REPORTS_DIR,
    load_config,
    setup_logging,
)
from fetchers.earnings import fetch_earnings
from fetchers.news import fetch_news
from fetchers.price import fetch_price
from fetchers.reddit import fetch_reddit
from fetchers.sec import fetch_sec
from analysis.formatter import format_context
from analysis.llm import analyze as llm_analyze
from output.terminal import render as terminal_render

logger = logging.getLogger(__name__)
console = Console()


def main() -> None:
    """Run the full analysis pipeline for a given ticker."""
    args = _parse_args()
    setup_logging(verbose=args.verbose)

    # ── Step 1: Load & validate configuration ─────────────────────────────────
    # load_config() raises SystemExit(2) if any required env var is missing.
    config = load_config()

    # Ensure runtime directories exist
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ticker = args.ticker.strip().upper()
    use_cache = not args.no_cache

    console.print(f"\n[bold blue]Analyzing {ticker}...[/bold blue]")

    # ── Step 2: Fetch price data (also validates the ticker) ──────────────────
    with console.status("[dim]Fetching price data...[/dim]"):
        try:
            price_data = fetch_price(ticker, use_cache=use_cache)
        except ValueError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            sys.exit(1)

    company_name = price_data.get("company_name") or ticker
    currency = price_data.get("currency") or "USD"
    cur = "C$" if currency == "CAD" else "$"
    current_price = price_data.get("current_price")
    price_str = f"{cur}{current_price:,.2f}" if current_price is not None else "N/A"
    console.print(
        f"[green]✓[/green] {company_name} — {price_str}  "
        f"[dim]({currency})[/dim]"
    )

    # ── Step 3: Fetch remaining data sources in parallel ──────────────────────
    def _run_news() -> dict[str, Any]:
        return fetch_news(
            ticker,
            company_name,
            config.finnhub_api_key,
            config.news_api_key,
            days=args.days,
            use_cache=use_cache,
        )

    def _run_reddit() -> dict[str, Any]:
        return fetch_reddit(ticker, days=args.days, use_cache=use_cache)

    def _run_sec() -> dict[str, Any]:
        return fetch_sec(
            ticker, config.edgar_user_agent, days=args.days, use_cache=use_cache
        )

    def _run_earnings() -> dict[str, Any]:
        return fetch_earnings(ticker, use_cache=use_cache)

    fetcher_fns: dict[str, Any] = {
        "news":     _run_news,
        "reddit":   _run_reddit,
        "sec":      _run_sec,
        "earnings": _run_earnings,
    }
    results: dict[str, dict[str, Any] | None] = {k: None for k in fetcher_fns}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_ids = {
            name: progress.add_task(f"[cyan]{name}[/cyan]", total=None)
            for name in fetcher_fns
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(fn): name
                for name, fn in fetcher_fns.items()
            }
            for future in concurrent.futures.as_completed(future_map):
                name = future_map[future]
                try:
                    results[name] = future.result()
                    progress.update(
                        task_ids[name],
                        description=f"[green]✓ {name}[/green]",
                        completed=1,
                        total=1,
                    )
                except Exception as exc:
                    logger.error(
                        f"[main] Fetcher '{name}' failed: {exc}", exc_info=args.verbose
                    )
                    progress.update(
                        task_ids[name],
                        description=f"[red]✗ {name} (failed)[/red]",
                        completed=1,
                        total=1,
                    )

    # Report which fetchers succeeded
    succeeded = [k for k, v in results.items() if v is not None]
    failed = [k for k, v in results.items() if v is None]
    if failed:
        console.print(
            f"[yellow]Warning:[/yellow] Some fetchers failed: {', '.join(failed)}. "
            "Analysis will proceed with available data."
        )
    if not succeeded:
        console.print(
            "[bold red]Error:[/bold red] All data fetchers failed — no data to analyze."
        )
        sys.exit(3)

    # Build well-formed fallback dicts for any failed fetchers
    news_data = results["news"] or _empty_news(ticker)
    reddit_data = results["reddit"] or _empty_reddit(ticker)
    sec_data = results["sec"] or _empty_sec(ticker)
    earnings_data = results["earnings"] or _empty_earnings(ticker)

    article_count = news_data.get("total_count", 0)
    post_count = len(reddit_data.get("posts") or [])
    filing_count = len(sec_data.get("filings") or [])
    console.print(
        f"[green]✓[/green] Fetched: {article_count} news articles, "
        f"{post_count} Reddit posts, {filing_count} SEC filings"
    )

    # ── Step 4: Format data bundle for LLM ────────────────────────────────────
    with console.status("[dim]Formatting context bundle...[/dim]"):
        context_bundle = format_context(
            price_data, news_data, reddit_data, sec_data, earnings_data
        )
    logger.debug(f"[main] Context bundle: {len(context_bundle):,} chars")

    # ── Step 5: LLM analysis ──────────────────────────────────────────────────
    with console.status("[dim]Analyzing with Claude (this may take 10-30s)...[/dim]"):
        # llm_analyze raises SystemExit(4) if all retries are exhausted
        analysis = llm_analyze(context_bundle, config.anthropic_api_key)

    # ── Step 6: Output ────────────────────────────────────────────────────────
    terminal_render(analysis, price_data, console=console)

    # File report generation (steps 11-12: not yet implemented)
    if not args.terminal_only:
        _generate_file_reports(analysis, price_data, output_dir, ticker, args.verbose)

    logger.info(f"[main] Analysis complete for {ticker}")


# ─── File Report Stubs ────────────────────────────────────────────────────────


def _generate_file_reports(
    analysis: dict[str, Any],
    price_data: dict[str, Any],
    output_dir: Path,
    ticker: str,
    verbose: bool,
) -> None:
    """Generate markdown and HTML report files.

    Attempts to import and call the markdown and HTML output modules.
    If those modules haven't been implemented yet (steps 11-12), prints
    a note and returns gracefully.
    """
    try:
        from output.markdown import render as md_render  # type: ignore[import]
        md_path = md_render(analysis, price_data, output_dir)
        console.print(f"[dim]Markdown report: {md_path}[/dim]")
    except ImportError:
        logger.debug("[main] output.markdown not yet available (step 11)")
    except Exception as exc:
        logger.warning(f"[main] Markdown report failed: {exc}", exc_info=verbose)

    try:
        from output.html import render as html_render  # type: ignore[import]
        html_path = html_render(analysis, price_data, output_dir)
        console.print(f"[dim]HTML report: {html_path}[/dim]")
    except ImportError:
        logger.debug("[main] output.html not yet available (step 12)")
    except Exception as exc:
        logger.warning(f"[main] HTML report failed: {exc}", exc_info=verbose)


# ─── Empty Fallback Dicts ─────────────────────────────────────────────────────


def _empty_news(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "articles": [],
        "total_count": 0,
        "finnhub_count": 0,
        "newsapi_count": 0,
        "fetch_timestamp": "",
    }


def _empty_reddit(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "posts": [],
        "stats": {
            "total_posts": 0,
            "avg_score": 0,
            "total_comments": 0,
            "subreddit_breakdown": {},
        },
        "fetch_timestamp": "",
    }


def _empty_sec(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "filings": [],
        "is_us_listed": True,
        "note": "Data unavailable due to fetcher error.",
        "fetch_timestamp": "",
    }


def _empty_earnings(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "next_earnings_date": None,
        "days_until_next": None,
        "last_quarter": {
            "period": None,
            "eps_estimate": None,
            "eps_actual": None,
            "eps_surprise_pct": None,
            "revenue_estimate": None,
            "revenue_actual": None,
            "beat_or_miss": "N/A",
        },
        "fetch_timestamp": "",
    }


# ─── CLI Argument Parser ──────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="analyze",
        description=(
            "Stock Sentiment Engine — aggregate news, Reddit, SEC filings, "
            "earnings, and price data for any stock ticker, then analyze with Claude."
        ),
    )
    parser.add_argument(
        "ticker",
        help="Stock ticker symbol (e.g. AAPL, SHOP.TO, RY.TO)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Force fresh data fetch, ignoring any cached results.",
    )
    parser.add_argument(
        "--terminal-only",
        action="store_true",
        default=False,
        help="Print to terminal only; do not generate Markdown or HTML report files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPORTS_DIR),
        metavar="DIR",
        help=f"Directory for saving report files (default: {REPORTS_DIR}).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        metavar="N",
        help=f"Days of historical news/data to fetch (default: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose/debug logging.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
