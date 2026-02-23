"""Shared file-based caching utilities for all fetchers.

Cache files are stored in the cache/ directory as JSON.
File naming: {TICKER}_{fetcher_name}_{YYYY-MM-DD}.json

Each fetcher calls these four functions directly:
    path = get_cache_path(ticker, "price")
    if use_cache and cache_is_valid(path):
        return load_cache(path)
    # ... fetch ...
    save_cache(path, result)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import CACHE_DIR, CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


def get_cache_path(ticker: str, fetcher_name: str) -> Path:
    """Return the cache file path for a given ticker and fetcher.

    Dots in the ticker symbol are replaced with underscores so the
    filename is safe on all platforms (e.g. SHOP.TO → SHOP_TO).
    The date portion is today's UTC date; combined with the TTL check
    in cache_is_valid, this means cache entries naturally expire at
    day boundaries as well.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "SHOP.TO").
        fetcher_name: Short identifier for the fetcher
            (e.g. "price", "news", "reddit", "sec", "earnings").

    Returns:
        Absolute path to the cache file (may not exist yet).
    """
    safe_ticker = ticker.replace(".", "_").upper()
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    filename = f"{safe_ticker}_{fetcher_name}_{date_str}.json"
    return CACHE_DIR / filename


def cache_is_valid(path: Path, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
    """Check whether a cache file exists and is within its TTL.

    Uses the filesystem modification time rather than storing a
    timestamp inside the JSON, so the cache utility has no schema
    dependency on the data it stores.

    Args:
        path: Path to the cache file.
        ttl_hours: Maximum age of the cache file in hours.
            Defaults to CACHE_TTL_HOURS from config.

    Returns:
        True if the file exists and was last modified within ttl_hours.
    """
    if not path.exists():
        return False
    age_seconds = (
        datetime.now(tz=timezone.utc).timestamp() - path.stat().st_mtime
    )
    return age_seconds < ttl_hours * 3600


def load_cache(path: Path) -> dict[str, Any]:
    """Load and return JSON data from a cache file.

    Args:
        path: Path to the cache file. Must exist.

    Returns:
        Deserialized JSON contents as a dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    logger.debug(f"Loading cache from {path.name}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_cache(path: Path, data: dict[str, Any]) -> None:
    """Serialize data to JSON and write it to the cache file.

    Creates the cache directory if it does not exist. Overwrites any
    existing file at the path. Uses default=str to safely serialize
    datetime and pandas Timestamp objects without requiring callers
    to manually convert them.

    Args:
        path: Destination path for the cache file.
        data: Data to serialize. Must be JSON-serializable (or contain
            only types that str() can handle).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Saving cache to {path.name}")
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
