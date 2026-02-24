"""Earnings data fetcher using yfinance.

Fetches the next earnings date, days until next earnings, and the most
recent quarter's EPS performance (estimate vs actual, beat/miss/in-line).

yfinance's earnings data availability varies by ticker — Canadian/TSX
stocks often have sparse or missing earnings info. All fields are
Optional and the fetcher never crashes the pipeline on missing data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from cache import cache_is_valid, get_cache_path, load_cache, save_cache
from config import CACHE_TTL_HOURS

logger = logging.getLogger(__name__)

FETCHER_NAME: str = "earnings"

# EPS surprise threshold — within this % is considered "in-line"
IN_LINE_THRESHOLD: float = 0.02


def fetch_earnings(
    ticker: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch earnings data for a ticker using yfinance.

    Retrieves the next scheduled earnings date and the most recent
    quarter's EPS performance. All numeric fields may be None if
    yfinance does not have data for the ticker.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "SHOP.TO").
        use_cache: If True, return cached data when available and valid.

    Returns:
        A dict with the following keys:
            ticker (str): The ticker symbol.
            next_earnings_date (str | None): Next earnings date as
                "YYYY-MM-DD", or None if unknown.
            days_until_next (int | None): Calendar days until next
                earnings, or None if the date is unknown.
            last_quarter (dict): Most recent quarter's performance:
                period (str | None): Date of the earnings report.
                eps_estimate (float | None): Consensus EPS estimate.
                eps_actual (float | None): Reported EPS.
                eps_surprise_pct (float | None): Surprise as a %.
                revenue_estimate (float | None): Revenue estimate.
                revenue_actual (float | None): Reported revenue.
                beat_or_miss (str): "Beat", "Miss", "In-line", or "N/A".
            fetch_timestamp (str): ISO-8601 UTC timestamp of the fetch.
    """
    cache_path = get_cache_path(ticker, FETCHER_NAME)

    if use_cache and cache_is_valid(cache_path, ttl_hours=CACHE_TTL_HOURS):
        logger.info(f"[earnings] Cache hit for {ticker}")
        return load_cache(cache_path)

    logger.info(f"[earnings] Fetching earnings data for {ticker}")
    result = _fetch_from_yfinance(ticker)

    save_cache(cache_path, result)
    return result


def _fetch_from_yfinance(ticker: str) -> dict[str, Any]:
    """Query yfinance and build the structured earnings data dict.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Structured earnings data dict.
    """
    yt = yf.Ticker(ticker)
    now = datetime.now(tz=timezone.utc)

    next_date, days_until = _get_next_earnings_date(yt, now)
    last_quarter = _get_last_quarter(yt, now)

    logger.debug(
        f"[earnings] {ticker}: next={next_date} ({days_until}d), "
        f"last_q={last_quarter.get('beat_or_miss')}"
    )

    return {
        "ticker": ticker,
        "next_earnings_date": next_date,
        "days_until_next": days_until,
        "last_quarter": last_quarter,
        "fetch_timestamp": now.isoformat(),
    }


def _get_next_earnings_date(
    yt: yf.Ticker,
    now: datetime,
) -> tuple[str | None, int | None]:
    """Extract the next scheduled earnings date from yfinance data.

    Tries earnings_dates first (most reliable), then falls back to
    the calendar dict.

    Args:
        yt: Initialised yfinance Ticker object.
        now: Current UTC datetime for comparison.

    Returns:
        Tuple of (date_str, days_until). Both are None if unavailable.
    """
    # Primary: earnings_dates DataFrame has both past and future rows
    try:
        df = yt.earnings_dates
        if df is not None and not df.empty:
            # earnings_dates is sorted descending; future dates appear at the top
            future = df[df.index.tz_convert(timezone.utc) > now]
            if not future.empty:
                # Take the nearest future date (smallest value in the future set)
                next_ts = future.index.min()
                next_ts_utc = next_ts.tz_convert(timezone.utc)
                next_date = next_ts_utc.strftime("%Y-%m-%d")
                days_until = max(0, (next_ts_utc - now).days)
                return next_date, days_until
    except Exception as exc:
        logger.debug(f"[earnings] earnings_dates lookup failed: {exc}")

    # Fallback: calendar dict / DataFrame
    try:
        cal = yt.calendar
        if cal is None:
            return None, None

        # yfinance returns calendar as either a dict or a DataFrame
        if hasattr(cal, "to_dict"):
            cal = cal.to_dict()

        earnings_dates = cal.get("Earnings Date", [])
        if not earnings_dates:
            return None, None

        # earnings_dates is a list of Timestamps; take the earliest future one
        if not isinstance(earnings_dates, list):
            earnings_dates = [earnings_dates]

        future_dates = [
            ts for ts in earnings_dates
            if hasattr(ts, "timestamp") and ts.timestamp() > now.timestamp()
        ]
        if not future_dates:
            return None, None

        next_ts = min(future_dates)
        next_date = next_ts.strftime("%Y-%m-%d")
        days_until = max(0, (next_ts.replace(tzinfo=timezone.utc) - now).days)
        return next_date, days_until

    except Exception as exc:
        logger.debug(f"[earnings] calendar fallback failed: {exc}")
        return None, None


def _get_last_quarter(
    yt: yf.Ticker,
    now: datetime,
) -> dict[str, Any]:
    """Extract the most recent quarter's EPS performance.

    Uses earnings_dates which contains both EPS estimates and actuals.
    Revenue data is not available from this source (yfinance does not
    expose revenue estimate vs actual in a reliable public API).

    Args:
        yt: Initialised yfinance Ticker object.
        now: Current UTC datetime for filtering past dates.

    Returns:
        Dict with keys: period, eps_estimate, eps_actual,
        eps_surprise_pct, revenue_estimate, revenue_actual, beat_or_miss.
    """
    empty = _empty_last_quarter()

    try:
        df = yt.earnings_dates
        if df is None or df.empty:
            return empty

        # Past rows have a Reported EPS (not NaN)
        past = df[df.index.tz_convert(timezone.utc) <= now]
        if past.empty:
            return empty

        # Most recent past row is first (descending sort)
        row = past.iloc[0]
        period = past.index[0].strftime("%Y-%m-%d")

        eps_est = _safe_float(row.get("EPS Estimate"))
        eps_act = _safe_float(row.get("Reported EPS"))
        surprise_pct = _safe_float(row.get("Surprise(%)"))

        beat_or_miss = _classify_beat_miss(eps_est, eps_act, surprise_pct)

        return {
            "period": period,
            "eps_estimate": eps_est,
            "eps_actual": eps_act,
            "eps_surprise_pct": surprise_pct,
            "revenue_estimate": None,
            "revenue_actual": None,
            "beat_or_miss": beat_or_miss,
        }

    except Exception as exc:
        logger.debug(f"[earnings] last_quarter extraction failed: {exc}")
        return empty


def _classify_beat_miss(
    eps_est: float | None,
    eps_act: float | None,
    surprise_pct: float | None,
) -> str:
    """Classify an earnings result as Beat, Miss, In-line, or N/A.

    Uses surprise_pct if available (most accurate). Falls back to
    computing the surprise from estimate and actual directly.

    Args:
        eps_est: Consensus EPS estimate.
        eps_act: Reported EPS.
        surprise_pct: Pre-computed surprise percentage from yfinance.

    Returns:
        "Beat", "Miss", "In-line", or "N/A".
    """
    # Use pre-computed surprise if available
    if surprise_pct is not None:
        if abs(surprise_pct) <= IN_LINE_THRESHOLD * 100:
            return "In-line"
        return "Beat" if surprise_pct > 0 else "Miss"

    # Compute from raw values
    if eps_est is None or eps_act is None:
        return "N/A"
    if eps_est == 0:
        return "N/A"

    diff_pct = (eps_act - eps_est) / abs(eps_est)
    if abs(diff_pct) <= IN_LINE_THRESHOLD:
        return "In-line"
    return "Beat" if diff_pct > 0 else "Miss"


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None if not possible.

    Args:
        value: Any value (float, int, str, NaN, None, etc.).

    Returns:
        Float value, or None if conversion fails or value is NaN.
    """
    if value is None:
        return None
    try:
        f = float(value)
        # pandas NaN check
        if f != f:  # NaN != NaN is always True
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _empty_last_quarter() -> dict[str, Any]:
    """Return an empty last_quarter dict with all None fields."""
    return {
        "period": None,
        "eps_estimate": None,
        "eps_actual": None,
        "eps_surprise_pct": None,
        "revenue_estimate": None,
        "revenue_actual": None,
        "beat_or_miss": "N/A",
    }
