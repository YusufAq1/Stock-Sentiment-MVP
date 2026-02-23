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
