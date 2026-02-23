"""Price data fetcher using yfinance.

Fetches current price statistics and 30-day OHLCV history for a given
stock ticker. Supports both US tickers (e.g. "AAPL") and TSX tickers
(e.g. "SHOP.TO") natively via yfinance. Results are cached as JSON
to avoid redundant API calls within the CACHE_TTL_HOURS window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import yfinance as yf

from cache import cache_is_valid, get_cache_path, load_cache, save_cache
from config import CACHE_TTL_HOURS

logger = logging.getLogger(__name__)

FETCHER_NAME: str = "price"
OHLCV_DAYS: int = 30  # Days of daily OHLCV history to fetch


def fetch_price(
    ticker: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch current price data and 30-day OHLCV history for a ticker.

    Queries yfinance for key statistics (price, P/E, market cap, etc.)
    and daily OHLCV bars. Results are cached as JSON; subsequent calls
    within CACHE_TTL_HOURS return cached data without hitting the API.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "SHOP.TO").
        use_cache: If True, return cached data when available and valid.
            A fresh fetch always writes a new cache entry.

    Returns:
        A dict with the following keys:
            symbol (str): The ticker symbol as provided.
            company_name (str): Full company name (empty string if unknown).
            sector (str): Sector classification (empty string if unknown).
            industry (str): Industry classification (empty string if unknown).
            currency (str): "USD" for US stocks, "CAD" for TSX stocks.
            current_price (Optional[float]): Most recent trading price.
            previous_close (Optional[float]): Previous session close.
            day_change_dollars (Optional[float]): Change in dollars vs prev close.
            day_change_percent (Optional[float]): Change as a percentage.
            week_52_high (Optional[float]): 52-week high price.
            week_52_low (Optional[float]): 52-week low price.
            market_cap (Optional[int]): Market capitalisation in local currency.
            volume_10day_avg (Optional[int]): 10-day average daily volume.
            volume_3month_avg (Optional[int]): 3-month average daily volume.
            pe_trailing (Optional[float]): Trailing twelve-month P/E ratio.
            pe_forward (Optional[float]): Forward P/E ratio.
            eps_trailing (Optional[float]): Trailing EPS.
            dividend_yield (Optional[float]): Annual dividend yield as decimal.
            beta (Optional[float]): Beta coefficient.
            ohlcv_30days (list[dict]): Daily OHLCV bars, oldest first.
                Each bar: {date, open, high, low, close, volume}.
            fetch_timestamp (str): ISO-8601 UTC timestamp of the fetch.

    Raises:
        ValueError: If the ticker does not resolve to a valid security.
            The caller (analyze.py) should catch this and exit with code 1.
    """
    cache_path = get_cache_path(ticker, FETCHER_NAME)

    if use_cache and cache_is_valid(cache_path, ttl_hours=CACHE_TTL_HOURS):
        logger.info(f"[price] Cache hit for {ticker}")
        return load_cache(cache_path)

    logger.info(f"[price] Fetching price data for {ticker}")
    result = _fetch_from_yfinance(ticker)

    save_cache(cache_path, result)
    return result


def _fetch_from_yfinance(ticker: str) -> dict[str, Any]:
    """Query yfinance and build the structured price data dict.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Structured price data dict matching the fetch_price return schema.

    Raises:
        ValueError: If yfinance returns no data for the ticker.
    """
    yt = yf.Ticker(ticker)
    info: dict[str, Any] = yt.info or {}

    # yfinance returns a sparse dict (e.g. {'trailingPegRatio': None}) for
    # invalid or delisted tickers rather than raising an exception. Detect
    # this with a two-step check: look for a price field, then fall back to
    # checking whether history returns any rows.
    current_price: Optional[float] = (
        info.get("regularMarketPrice") or info.get("currentPrice")
    )
    if current_price is None:
        hist_check = yt.history(period="5d")
        if hist_check.empty:
            raise ValueError(
                f"Ticker '{ticker}' did not resolve to a valid security. "
                f"Check the symbol and try again."
            )
        # History exists but info is sparse — try to get price from history
        if not hist_check.empty:
            current_price = float(hist_check["Close"].iloc[-1])

    previous_close: Optional[float] = (
        info.get("previousClose") or info.get("regularMarketPreviousClose")
    )

    day_change_dollars: Optional[float] = None
    day_change_percent: Optional[float] = None
    if current_price is not None and previous_close is not None:
        day_change_dollars = round(current_price - previous_close, 4)
        day_change_percent = round(
            (day_change_dollars / previous_close) * 100, 4
        )

    ohlcv = _fetch_ohlcv(yt, ticker)

    result: dict[str, Any] = {
        "symbol": ticker,
        "company_name": info.get("longName") or info.get("shortName") or "",
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "currency": info.get("currency") or "USD",
        "current_price": current_price,
        "previous_close": previous_close,
        "day_change_dollars": day_change_dollars,
        "day_change_percent": day_change_percent,
        "week_52_high": info.get("fiftyTwoWeekHigh"),
        "week_52_low": info.get("fiftyTwoWeekLow"),
        "market_cap": info.get("marketCap"),
        "volume_10day_avg": (
            info.get("averageVolume10days") or info.get("averageDailyVolume10Day")
        ),
        "volume_3month_avg": info.get("averageVolume"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "eps_trailing": info.get("trailingEps"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "ohlcv_30days": ohlcv,
        "fetch_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    logger.debug(
        f"[price] {ticker}: price={current_price} "
        f"currency={result['currency']} bars={len(ohlcv)}"
    )
    return result


def _fetch_ohlcv(yt: yf.Ticker, ticker: str) -> list[dict[str, Any]]:
    """Fetch OHLCV_DAYS days of daily OHLCV bars from yfinance.

    Failures here are non-fatal — the function returns an empty list
    and logs a warning so the rest of the price data is still usable.

    Args:
        yt: An already-initialised yfinance Ticker object.
        ticker: Ticker symbol used only for log messages.

    Returns:
        List of daily OHLCV bar dicts ordered oldest to newest.
        Empty list if the fetch fails or returns no data.
    """
    try:
        hist = yt.history(period=f"{OHLCV_DAYS}d", interval="1d")
        if hist.empty:
            logger.warning(f"[price] No OHLCV history returned for {ticker}")
            return []

        bars: list[dict[str, Any]] = []
        for ts, row in hist.iterrows():
            bars.append(
                {
                    "date": ts.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                }
            )
        return bars

    except Exception as exc:
        logger.warning(f"[price] Failed to fetch OHLCV for {ticker}: {exc}")
        return []
