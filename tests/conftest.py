"""Shared pytest fixtures and configuration for the test suite.

Fixtures defined here are automatically available to all test modules
without any explicit import. Add mock API response fixtures here as
each fetcher is built (Steps 3–6).
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
