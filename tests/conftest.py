"""Shared pytest fixtures and configuration for the test suite.

Fixtures defined here are automatically available to all test modules
without any explicit import. Add mock API response fixtures here as
each fetcher is built (Steps 3–6).

Reddit data is fetched via the public JSON API — no auth fixtures needed.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_ticker_us() -> str:
    """A well-known US ticker used across fetcher tests."""
    return "AAPL"


@pytest.fixture
def sample_ticker_tsx() -> str:
    """A well-known TSX ticker for testing Canadian market handling."""
    return "SHOP.TO"


@pytest.fixture
def mock_price_data() -> dict:
    """Canonical price data dict matching the fetch_price return schema.

    Used as the source of truth for the expected shape of fetch_price
    output. Referenced in test_fetchers.py (to validate the real
    fetcher) and in test_formatter.py (as input to the formatter).
    """
    return {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "currency": "USD",
        "current_price": 241.53,
        "previous_close": 238.87,
        "day_change_dollars": 2.66,
        "day_change_percent": 1.11,
        "week_52_high": 260.10,
        "week_52_low": 164.08,
        "market_cap": 3_600_000_000_000,
        "volume_10day_avg": 55_000_000,
        "volume_3month_avg": 62_000_000,
        "pe_trailing": 32.5,
        "pe_forward": 28.1,
        "eps_trailing": 7.43,
        "dividend_yield": 0.0044,
        "beta": 1.24,
        "ohlcv_30days": [
            {
                "date": "2026-01-23",
                "open": 235.10,
                "high": 242.00,
                "low": 234.50,
                "close": 241.53,
                "volume": 58_000_000,
            }
        ],
        "fetch_timestamp": "2026-02-22T20:00:00+00:00",
    }


@pytest.fixture
def mock_reddit_data() -> dict:
    """Canonical Reddit data dict matching the fetch_reddit return schema.

    Used as the source of truth for the expected shape of fetch_reddit
    output. Referenced in test_fetchers.py and test_formatter.py.
    """
    return {
        "ticker": "AAPL",
        "posts": [
            {
                "id": "abc123",
                "title": "AAPL earnings beat — what's everyone's take?",
                "body": "Apple just crushed Q1 estimates. EPS beat by 5%, revenue up 6% YoY.",
                "score": 1523,
                "num_comments": 342,
                "created_utc": 1737590400.0,
                "subreddit": "wallstreetbets",
                "url": "https://www.reddit.com/r/wallstreetbets/comments/abc123/",
                "top_comments": [
                    {"body": "Been holding since $150, not selling.", "score": 412},
                    {"body": "Services revenue is the real story here.", "score": 287},
                ],
            },
            {
                "id": "def456",
                "title": "Is AAPL still a buy at these levels?",
                "body": "P/E is getting stretched but the buyback machine keeps running.",
                "score": 634,
                "num_comments": 89,
                "created_utc": 1737504000.0,
                "subreddit": "stocks",
                "url": "https://www.reddit.com/r/stocks/comments/def456/",
                "top_comments": [
                    {"body": "Valuation is rich but quality commands a premium.", "score": 95},
                ],
            },
        ],
        "stats": {
            "total_posts": 2,
            "avg_score": 1078.5,
            "total_comments": 431,
            "subreddit_breakdown": {"wallstreetbets": 1, "stocks": 1},
        },
        "fetch_timestamp": "2026-02-22T20:00:00+00:00",
    }


@pytest.fixture
def mock_news_data() -> dict:
    """Canonical news data dict matching the fetch_news return schema.

    Used as the source of truth for the expected shape of fetch_news
    output. Referenced in test_fetchers.py and test_formatter.py.
    """
    return {
        "ticker": "AAPL",
        "articles": [
            {
                "title": "Apple Reports Record Q1 Revenue of $124 Billion",
                "summary": "Apple Inc. beat analyst expectations with record quarterly revenue driven by strong iPhone and Services growth.",
                "source": "Reuters",
                "url": "https://www.reuters.com/technology/apple-q1-results-2026",
                "published_at": "2026-02-21T18:00:00+00:00",
                "category": "technology",
                "provider": "finnhub",
            },
            {
                "title": "Apple's Services Segment Hits $26B in Quarterly Revenue",
                "summary": "The high-margin Services division continues to be Apple's fastest-growing business unit.",
                "source": "Bloomberg",
                "url": "https://www.bloomberg.com/news/apple-services-2026",
                "published_at": "2026-02-20T12:00:00+00:00",
                "category": "",
                "provider": "newsapi",
            },
        ],
        "total_count": 2,
        "finnhub_count": 1,
        "newsapi_count": 1,
        "fetch_timestamp": "2026-02-22T20:00:00+00:00",
    }


@pytest.fixture
def mock_sec_data() -> dict:
    """Canonical SEC data dict matching the fetch_sec return schema.

    Represents a US-listed ticker with one 8-K and one 10-Q filing.
    """
    return {
        "ticker": "AAPL",
        "filings": [
            {
                "form_type": "8-K",
                "filing_date": "2026-02-01",
                "description": "Current Report",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.htm",
                "content": "Apple Inc. reported record first quarter results. Revenue was $124.3 billion, up 4% year over year.",
            },
            {
                "form_type": "10-Q",
                "filing_date": "2026-01-30",
                "description": "Quarterly Report",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000002/0000320193-26-000002-index.htm",
                "content": None,
            },
        ],
        "is_us_listed": True,
        "note": "",
        "fetch_timestamp": "2026-02-22T20:00:00+00:00",
    }


@pytest.fixture
def mock_sec_data_tsx() -> dict:
    """SEC data dict for a TSX-listed ticker — empty filings, non-US note."""
    return {
        "ticker": "SHOP.TO",
        "filings": [],
        "is_us_listed": False,
        "note": "No SEC filings (non-US listed security)",
        "fetch_timestamp": "2026-02-22T20:00:00+00:00",
    }


@pytest.fixture
def mock_earnings_data() -> dict:
    """Canonical earnings data dict matching the fetch_earnings return schema."""
    return {
        "ticker": "AAPL",
        "next_earnings_date": "2026-04-30",
        "days_until_next": 67,
        "last_quarter": {
            "period": "2026-01-29",
            "eps_estimate": 2.35,
            "eps_actual": 2.40,
            "eps_surprise_pct": 2.13,
            "revenue_estimate": None,
            "revenue_actual": None,
            "beat_or_miss": "Beat",
        },
        "fetch_timestamp": "2026-02-22T20:00:00+00:00",
    }
