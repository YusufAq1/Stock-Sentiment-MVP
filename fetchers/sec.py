"""SEC EDGAR filings fetcher.

Looks up a company's CIK via the EDGAR company tickers file, then
fetches recent 10-K, 10-Q, and 8-K filings from the submissions API.
For 8-K filings, attempts to fetch and return the plain-text content.

TSX and other non-US tickers gracefully return an empty result — they
file with SEDAR/local regulators, not the SEC.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from cache import cache_is_valid, get_cache_path, load_cache, save_cache
from config import (
    CACHE_TTL_HOURS,
    DEFAULT_DAYS,
    EDGAR_SUBMISSIONS_URL,
)

logger = logging.getLogger(__name__)

FETCHER_NAME: str = "sec"

# The company tickers file changes rarely — cache it much longer than API data.
COMPANY_TICKERS_CACHE_TTL: int = 24  # hours

# Source URLs
COMPANY_TICKERS_URL: str = "https://www.sec.gov/files/company_tickers.json"
EDGAR_ARCHIVES_BASE: str = "https://www.sec.gov/Archives/edgar/data"

# Filings we care about
TARGET_FORMS: frozenset[str] = frozenset({"10-K", "10-Q", "8-K"})

# Known non-US exchange suffixes — tickers ending in these have no SEC filings.
# Single-letter US class suffixes (A, B, C) are intentionally excluded.
NON_US_SUFFIXES: frozenset[str] = frozenset({
    "TO", "V", "CN",          # Canadian (TSX, TSX-V, NEO)
    "L",                       # London Stock Exchange
    "PA", "AS", "BR", "DE",   # European exchanges
    "T", "TYO",                # Tokyo
    "AX",                      # Australia (ASX)
    "HK",                      # Hong Kong
    "SS", "SZ",                # Shanghai, Shenzhen
})


def fetch_sec(
    ticker: str,
    edgar_user_agent: str,
    days: int = DEFAULT_DAYS,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch recent SEC filings for a ticker from EDGAR.

    Returns 10-K, 10-Q, and 8-K filings filed within the last `days` days.
    For 8-K filings, attempts to include the plain-text content.
    Non-US tickers (e.g. TSX stocks ending in .TO) return an empty result
    with an explanatory note rather than raising an error.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "SHOP.TO").
        edgar_user_agent: User-Agent header value required by EDGAR
            (e.g. "stock-sentiment-engine/1.0 you@email.com").
        days: How many days back to look for filings.
        use_cache: If True, return cached data when available and valid.

    Returns:
        A dict with the following keys:
            ticker (str): The ticker symbol.
            filings (list[dict]): List of filing dicts, each with:
                form_type, filing_date, description, url, content.
                content is a string for 8-K filings (may be None if
                the document could not be fetched), None for 10-K/10-Q.
            is_us_listed (bool): False for non-US tickers.
            note (str): Explanatory note (e.g. for non-US tickers or
                when no filings are found).
            fetch_timestamp (str): ISO-8601 UTC timestamp of the fetch.
    """
    # Non-US tickers will never have SEC filings — return gracefully.
    if _is_non_us_ticker(ticker):
        logger.info(f"[sec] {ticker} is non-US listed — skipping EDGAR")
        return _empty_result(
            ticker,
            is_us_listed=False,
            note="No SEC filings (non-US listed security)",
        )

    cache_path = get_cache_path(ticker, FETCHER_NAME)
    if use_cache and cache_is_valid(cache_path, ttl_hours=CACHE_TTL_HOURS):
        logger.info(f"[sec] Cache hit for {ticker}")
        return load_cache(cache_path)

    logger.info(f"[sec] Fetching SEC filings for {ticker} (last {days} days)")
    result = _fetch_from_edgar(ticker, edgar_user_agent, days, use_cache)

    save_cache(cache_path, result)
    return result


def _fetch_from_edgar(
    ticker: str,
    edgar_user_agent: str,
    days: int,
    use_cache: bool,
) -> dict[str, Any]:
    """Query EDGAR for company filings.

    Args:
        ticker: Stock ticker symbol (no exchange suffix).
        edgar_user_agent: EDGAR User-Agent header value.
        days: Look-back window in days.
        use_cache: Whether to use cache for the company tickers lookup.

    Returns:
        Structured filings result dict.
    """
    headers = {"User-Agent": edgar_user_agent}
    now = datetime.now(tz=timezone.utc)
    start_str = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")

    with httpx.Client(headers=headers, timeout=15.0) as client:
        cik = _get_cik(ticker, client, use_cache)
        if cik is None:
            note = (
                f"No SEC filings found for '{ticker}'. "
                "If this is a non-US listed security, this is expected."
            )
            return _empty_result(ticker, is_us_listed=True, note=note)

        filings = _get_recent_filings(cik, client, start_str, end_str)

        # Attempt to fetch content for 8-K filings
        for filing in filings:
            if filing["form_type"] == "8-K":
                filing["content"] = _fetch_8k_content(
                    cik, filing["accession_number"], filing["primary_doc"], client
                )
            # Remove the internal key we no longer need
            filing.pop("accession_number", None)
            filing.pop("primary_doc", None)

    logger.debug(f"[sec] {ticker} (CIK {cik}): {len(filings)} filings found")

    return {
        "ticker": ticker,
        "filings": filings,
        "is_us_listed": True,
        "note": "" if filings else f"No recent filings in the last {days} days.",
        "fetch_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _get_cik(
    ticker: str,
    client: httpx.Client,
    use_cache: bool,
) -> int | None:
    """Resolve a ticker symbol to an EDGAR CIK integer.

    Downloads and caches the EDGAR company tickers file, then does a
    case-insensitive lookup. The ticker suffix is stripped before lookup
    (e.g. "SHOP.TO" → "SHOP").

    Args:
        ticker: Stock ticker symbol.
        client: Shared httpx client.
        use_cache: Whether to read from cache.

    Returns:
        CIK as an integer, or None if not found.
    """
    # Use a fixed key for the shared tickers file cache
    cache_path = get_cache_path("SEC_COMPANY_TICKERS", "meta")

    if use_cache and cache_is_valid(cache_path, ttl_hours=COMPANY_TICKERS_CACHE_TTL):
        tickers_data = load_cache(cache_path)
    else:
        try:
            response = client.get(COMPANY_TICKERS_URL, timeout=20.0)
            if response.status_code != 200:
                logger.warning(
                    f"[sec] company_tickers.json returned HTTP {response.status_code}"
                )
                return None
            tickers_data = response.json()
            save_cache(cache_path, tickers_data)
        except Exception as exc:
            logger.warning(f"[sec] Failed to fetch company_tickers.json: {exc}")
            return None

    clean_ticker = ticker.split(".")[0].upper()
    for entry in tickers_data.values():
        if isinstance(entry, dict) and entry.get("ticker", "").upper() == clean_ticker:
            return int(entry["cik_str"])

    logger.debug(f"[sec] Ticker '{clean_ticker}' not found in EDGAR company list")
    return None


def _get_recent_filings(
    cik: int,
    client: httpx.Client,
    start_str: str,
    end_str: str,
) -> list[dict[str, Any]]:
    """Fetch and filter recent filings from the EDGAR submissions API.

    Args:
        cik: Company CIK integer.
        client: Shared httpx client.
        start_str: Start date as "YYYY-MM-DD".
        end_str: End date as "YYYY-MM-DD".

    Returns:
        List of filing dicts (form_type, filing_date, description, url,
        accession_number, primary_doc, content). Empty list on error.
    """
    cik_padded = str(cik).zfill(10)
    url = f"{EDGAR_SUBMISSIONS_URL}/CIK{cik_padded}.json"

    try:
        response = client.get(url)
        if response.status_code != 200:
            logger.warning(f"[sec] Submissions API returned HTTP {response.status_code}")
            return []

        data = response.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        acc_nos = recent.get("accessionNumber", [])
        descriptions = recent.get("primaryDocDescription", [])
        primary_docs = recent.get("primaryDocument", [])

        filings: list[dict[str, Any]] = []
        for form, date, acc_no, desc, primary_doc in zip(
            forms, dates, acc_nos, descriptions, primary_docs
        ):
            if form not in TARGET_FORMS:
                continue
            if not (start_str <= date <= end_str):
                continue

            acc_no_nodashes = acc_no.replace("-", "")
            filing_url = (
                f"{EDGAR_ARCHIVES_BASE}/{cik}/{acc_no_nodashes}/"
                f"{acc_no}-index.htm"
            )

            filings.append(
                {
                    "form_type": form,
                    "filing_date": date,
                    "description": desc or "",
                    "url": filing_url,
                    "content": None,
                    # Internal keys used for 8-K content fetch — removed before return
                    "accession_number": acc_no,
                    "primary_doc": primary_doc or "",
                }
            )

        return filings

    except Exception as exc:
        logger.warning(f"[sec] Error fetching submissions for CIK {cik}: {exc}")
        return []


def _fetch_8k_content(
    cik: int,
    acc_no: str,
    primary_doc: str,
    client: httpx.Client,
) -> str | None:
    """Attempt to fetch and return plain-text content of an 8-K filing.

    8-K filings are typically short material event disclosures that fit
    well within the LLM context window. The content is HTML-stripped and
    truncated to 3000 characters.

    Args:
        cik: Company CIK integer.
        acc_no: Accession number (e.g. "0000320193-26-000001").
        primary_doc: Primary document filename (e.g. "0000320193-26-000001.htm").
        client: Shared httpx client.

    Returns:
        Plain-text content string, truncated to 3000 chars,
        or None if the document could not be fetched.
    """
    if not primary_doc:
        return None

    acc_no_nodashes = acc_no.replace("-", "")
    doc_url = f"{EDGAR_ARCHIVES_BASE}/{cik}/{acc_no_nodashes}/{primary_doc}"

    try:
        response = client.get(doc_url, timeout=10.0)
        if response.status_code != 200:
            return None

        text = _strip_html(response.text)
        # Collapse whitespace
        text = " ".join(text.split())
        return text[:3000] if len(text) > 3000 else text or None

    except Exception as exc:
        logger.debug(f"[sec] Could not fetch 8-K content from {doc_url}: {exc}")
        return None


def _is_non_us_ticker(ticker: str) -> bool:
    """Return True if the ticker has a known non-US exchange suffix.

    US share class suffixes (single letters like A, B, C in BRK.A) are
    not in NON_US_SUFFIXES so they correctly return False.

    Args:
        ticker: Stock ticker symbol (e.g. "SHOP.TO", "BRK.A", "AAPL").

    Returns:
        True if the suffix indicates a non-US listed security.
    """
    parts = ticker.upper().split(".")
    return len(parts) >= 2 and parts[-1] in NON_US_SUFFIXES


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities from a string.

    Args:
        html: Raw HTML content string.

    Returns:
        Plain-text string with tags removed.
    """
    # Drop script and style blocks entirely
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(r"<[^>]+>", " ", html)
    html = (
        html.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return html


def _empty_result(
    ticker: str,
    is_us_listed: bool,
    note: str,
) -> dict[str, Any]:
    """Return a well-formed empty result dict.

    Args:
        ticker: Stock ticker symbol.
        is_us_listed: Whether the ticker is a US-listed security.
        note: Explanatory note for the caller/LLM.

    Returns:
        Empty filings result dict with fetch timestamp.
    """
    return {
        "ticker": ticker,
        "filings": [],
        "is_us_listed": is_us_listed,
        "note": note,
        "fetch_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
