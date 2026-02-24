"""News article fetcher using Finnhub and NewsAPI.

Queries both sources for news about a ticker over a given date range,
merges the results, deduplicates by URL, sorts by date descending,
and caps at MAX_ARTICLES. Results are cached as JSON.

Finnhub covers financial news with per-company endpoints.
NewsAPI covers broader media using keyword search against company name.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from cache import cache_is_valid, get_cache_path, load_cache, save_cache
from config import (
    CACHE_TTL_HOURS,
    DEFAULT_DAYS,
    FINNHUB_BASE_URL,
    MAX_ARTICLES,
    NEWSAPI_BASE_URL,
)

logger = logging.getLogger(__name__)

FETCHER_NAME: str = "news"


def fetch_news(
    ticker: str,
    company_name: str,
    finnhub_api_key: str,
    news_api_key: str,
    days: int = DEFAULT_DAYS,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch news articles for a ticker from Finnhub and NewsAPI.

    Queries both sources, merges results, deduplicates by URL, sorts
    by publication date descending, and caps at MAX_ARTICLES total.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "SHOP.TO").
        company_name: Full company name used as the primary NewsAPI
            search query (e.g. "Apple Inc."). Falls back to the ticker
            symbol if empty.
        finnhub_api_key: Finnhub API key.
        news_api_key: NewsAPI key.
        days: How many days back to search for news.
        use_cache: If True, return cached data when available and valid.

    Returns:
        A dict with the following keys:
            ticker (str): The ticker symbol.
            articles (list[dict]): Merged, deduplicated articles sorted
                newest first. Each article has: title, summary, source,
                url, published_at (ISO-8601), category, provider.
            total_count (int): Number of articles returned.
            finnhub_count (int): Articles sourced from Finnhub.
            newsapi_count (int): Articles sourced from NewsAPI.
            fetch_timestamp (str): ISO-8601 UTC timestamp of the fetch.
    """
    cache_path = get_cache_path(ticker, FETCHER_NAME)

    if use_cache and cache_is_valid(cache_path, ttl_hours=CACHE_TTL_HOURS):
        logger.info(f"[news] Cache hit for {ticker}")
        return load_cache(cache_path)

    logger.info(f"[news] Fetching news for {ticker} (last {days} days)")

    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")

    with httpx.Client(timeout=15.0) as client:
        finnhub_articles = _fetch_finnhub(
            client, ticker, start_str, end_str, finnhub_api_key
        )
        newsapi_articles = _fetch_newsapi(
            client, ticker, company_name, start_str, news_api_key
        )

    finnhub_count = len(finnhub_articles)
    newsapi_count = len(newsapi_articles)

    merged = _deduplicate_and_sort(finnhub_articles + newsapi_articles)

    logger.debug(
        f"[news] {ticker}: {finnhub_count} Finnhub + {newsapi_count} NewsAPI "
        f"→ {len(merged)} after dedup"
    )

    result: dict[str, Any] = {
        "ticker": ticker,
        "articles": merged,
        "total_count": len(merged),
        "finnhub_count": finnhub_count,
        "newsapi_count": newsapi_count,
        "fetch_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    save_cache(cache_path, result)
    return result


def _fetch_finnhub(
    client: httpx.Client,
    ticker: str,
    start_str: str,
    end_str: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch company news from the Finnhub /company-news endpoint.

    TSX tickers have their exchange suffix stripped (e.g. "SHOP.TO" →
    "SHOP") since Finnhub uses plain symbols only.

    Args:
        client: Shared httpx client.
        ticker: Stock ticker symbol.
        start_str: Start date as "YYYY-MM-DD".
        end_str: End date as "YYYY-MM-DD".
        api_key: Finnhub API key.

    Returns:
        List of normalised article dicts. Empty list on any error.
    """
    # Finnhub uses plain symbols — strip exchange suffixes
    symbol = ticker.split(".")[0]

    url = f"{FINNHUB_BASE_URL}/company-news"
    params = {
        "symbol": symbol,
        "from": start_str,
        "to": end_str,
        "token": api_key,
    }

    try:
        response = client.get(url, params=params)

        if response.status_code == 429:
            logger.warning("[news] Finnhub rate limit hit — skipping Finnhub")
            return []
        if response.status_code == 401:
            logger.warning(
                "[news] Finnhub returned 401 — check that FINNHUB_API_KEY in .env is valid"
            )
            return []
        if response.status_code != 200:
            logger.warning(f"[news] Finnhub returned HTTP {response.status_code}")
            return []

        raw = response.json()
        if not isinstance(raw, list):
            logger.warning("[news] Finnhub response was not a list — skipping")
            return []

        articles: list[dict[str, Any]] = []
        for item in raw:
            url_val = item.get("url", "")
            if not url_val:
                continue
            published_at = _unix_to_iso(item.get("datetime"))
            articles.append(
                {
                    "title": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "source": item.get("source", ""),
                    "url": url_val,
                    "published_at": published_at,
                    "category": item.get("category", ""),
                    "provider": "finnhub",
                }
            )

        logger.debug(f"[news] Finnhub returned {len(articles)} articles for {symbol}")
        return articles

    except httpx.RequestError as exc:
        logger.warning(f"[news] Finnhub request error: {exc}")
        return []
    except Exception as exc:
        logger.warning(f"[news] Finnhub unexpected error: {exc}")
        return []


def _fetch_newsapi(
    client: httpx.Client,
    ticker: str,
    company_name: str,
    start_str: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch articles from NewsAPI /everything using company name or ticker.

    Uses company_name as the primary query for better relevance. Falls
    back to the bare ticker symbol if company_name is empty.

    Args:
        client: Shared httpx client.
        ticker: Stock ticker symbol (used as fallback query).
        company_name: Full company name for the primary search query.
        start_str: Start date as "YYYY-MM-DD".
        api_key: NewsAPI key.

    Returns:
        List of normalised article dicts. Empty list on any error.
    """
    # Strip exchange suffix and quotes from company name for cleaner query
    query = company_name.strip() if company_name.strip() else ticker.split(".")[0]
    # Remove legal suffixes that add noise (Inc., Corp., Ltd., etc.)
    for suffix in (" Inc.", " Inc", " Corp.", " Corp", " Ltd.", " Ltd", " LLC"):
        query = query.replace(suffix, "")
    query = query.strip()

    url = f"{NEWSAPI_BASE_URL}/everything"
    params = {
        "q": query,
        "from": start_str,
        "sortBy": "relevancy",
        "language": "en",
        "apiKey": api_key,
        "pageSize": 100,  # max per request on free tier
    }

    try:
        response = client.get(url, params=params)

        if response.status_code == 429:
            logger.warning("[news] NewsAPI rate limit hit — skipping NewsAPI")
            return []
        if response.status_code == 401:
            logger.warning(
                "[news] NewsAPI returned 401 — check that NEWS_API_KEY in .env is valid"
            )
            return []
        if response.status_code != 200:
            logger.warning(f"[news] NewsAPI returned HTTP {response.status_code}")
            return []

        data = response.json()
        raw_articles = data.get("articles", [])

        articles: list[dict[str, Any]] = []
        for item in raw_articles:
            url_val = (item.get("url") or "").strip()
            if not url_val or url_val == "https://removed.com":
                continue
            articles.append(
                {
                    "title": item.get("title") or "",
                    "summary": item.get("description") or "",
                    "source": (item.get("source") or {}).get("name", ""),
                    "url": url_val,
                    "published_at": item.get("publishedAt") or "",
                    "category": "",
                    "provider": "newsapi",
                }
            )

        logger.debug(f"[news] NewsAPI returned {len(articles)} articles for '{query}'")
        return articles

    except httpx.RequestError as exc:
        logger.warning(f"[news] NewsAPI request error: {exc}")
        return []
    except Exception as exc:
        logger.warning(f"[news] NewsAPI unexpected error: {exc}")
        return []


def _deduplicate_and_sort(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate articles by URL, sort newest first, cap at MAX_ARTICLES.

    When the same URL appears in both Finnhub and NewsAPI results, the
    Finnhub version is kept (it usually has a richer summary field).
    Since Finnhub articles are prepended to the list before this function
    is called, the first occurrence wins during deduplication.

    Args:
        articles: Combined unsorted list of article dicts from all sources.

    Returns:
        Deduplicated list sorted by published_at descending,
        capped at MAX_ARTICLES.
    """
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for article in articles:
        url = article.get("url", "").strip().rstrip("/")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(article)

    # Sort by published_at descending; empty strings sort last
    unique.sort(key=lambda a: a.get("published_at") or "", reverse=True)

    return unique[:MAX_ARTICLES]


def _unix_to_iso(timestamp: Any) -> str:
    """Convert a Unix timestamp (int or float) to an ISO-8601 UTC string.

    Args:
        timestamp: Unix timestamp value, or None.

    Returns:
        ISO-8601 string (e.g. "2026-02-21T14:30:00+00:00"),
        or empty string if the input is None or invalid.
    """
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""
