"""Reddit social sentiment fetcher using the public Reddit JSON API.

No credentials are required. Reddit exposes its public subreddit data
as JSON by appending `.json` to any Reddit URL. A descriptive User-Agent
header is set to avoid throttling.

Searches wallstreetbets, stocks, investing, and options for the ticker
symbol, fetches the top posts and their top comments, then deduplicates
and returns a structured summary dict.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from cache import cache_is_valid, get_cache_path, load_cache, save_cache
from config import (
    CACHE_TTL_HOURS,
    MAX_REDDIT_COMMENTS,
    MAX_REDDIT_POSTS,
    REDDIT_BASE_URL,
    REDDIT_POSTS_PER_SUB,
    REDDIT_REQUEST_DELAY,
    REDDIT_USER_AGENT,
    SUBREDDITS,
)

logger = logging.getLogger(__name__)

FETCHER_NAME: str = "reddit"


def fetch_reddit(
    ticker: str,
    days: int = 30,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch Reddit posts and comments mentioning a ticker symbol.

    Searches each subreddit in SUBREDDITS for the ticker, fetches the
    top comments for each post, deduplicates across subreddits, and
    returns a structured dict with posts and summary statistics.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "SHOP.TO").
        days: Look-back window passed to Reddit's time_filter. Reddit
            supports "day", "week", "month", "year", "all". Values up
            to 7 map to "week", up to 30 map to "month", otherwise "year".
        use_cache: If True, return cached data when available and valid.

    Returns:
        A dict with the following keys:
            ticker (str): The ticker symbol.
            posts (list[dict]): Deduplicated posts sorted by score desc.
                Each post: {id, title, body, score, num_comments,
                created_utc, subreddit, url, top_comments}.
            stats (dict): Summary statistics — total_posts, avg_score,
                total_comments, subreddit_breakdown.
            fetch_timestamp (str): ISO-8601 UTC timestamp of the fetch.
    """
    cache_path = get_cache_path(ticker, FETCHER_NAME)

    if use_cache and cache_is_valid(cache_path, ttl_hours=CACHE_TTL_HOURS):
        logger.info(f"[reddit] Cache hit for {ticker}")
        return load_cache(cache_path)

    logger.info(f"[reddit] Fetching Reddit posts for {ticker}")
    result = _fetch_from_reddit(ticker, days)

    save_cache(cache_path, result)
    return result


def _fetch_from_reddit(ticker: str, days: int) -> dict[str, Any]:
    """Query the Reddit JSON API and build the structured result dict.

    Args:
        ticker: Stock ticker symbol.
        days: Look-back window in days.

    Returns:
        Structured Reddit data dict.
    """
    time_filter = _days_to_time_filter(days)
    # Strip exchange suffix for search (e.g. "SHOP.TO" → "SHOP")
    search_query = ticker.split(".")[0]

    headers = {"User-Agent": REDDIT_USER_AGENT}
    seen_ids: set[str] = set()
    all_posts: list[dict[str, Any]] = []

    with httpx.Client(headers=headers, timeout=15.0) as client:
        for subreddit in SUBREDDITS:
            posts = _search_subreddit(
                client, subreddit, search_query, time_filter
            )
            for post in posts:
                if post["id"] not in seen_ids:
                    seen_ids.add(post["id"])
                    all_posts.append(post)
            # Polite delay between subreddit searches
            time.sleep(REDDIT_REQUEST_DELAY)

        # Fetch top comments for each unique post
        for post in all_posts:
            post["top_comments"] = _fetch_top_comments(
                client, post["subreddit"], post["id"]
            )
            time.sleep(REDDIT_REQUEST_DELAY)

    # Sort by score descending and cap total
    all_posts.sort(key=lambda p: p["score"], reverse=True)
    all_posts = all_posts[:MAX_REDDIT_POSTS]

    stats = _compute_stats(all_posts)

    logger.debug(
        f"[reddit] {ticker}: {len(all_posts)} posts across "
        f"{len(SUBREDDITS)} subreddits"
    )

    return {
        "ticker": ticker,
        "posts": all_posts,
        "stats": stats,
        "fetch_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _search_subreddit(
    client: httpx.Client,
    subreddit: str,
    query: str,
    time_filter: str,
) -> list[dict[str, Any]]:
    """Search a single subreddit for posts matching the query.

    Args:
        client: Shared httpx client with User-Agent header set.
        subreddit: Subreddit name without the r/ prefix.
        query: Search query string (ticker symbol).
        time_filter: Reddit time filter string ("week", "month", "year").

    Returns:
        List of post dicts from this subreddit. Empty list on any error.
    """
    url = f"{REDDIT_BASE_URL}/r/{subreddit}/search.json"
    params = {
        "q": query,
        "sort": "relevance",
        "t": time_filter,
        "limit": REDDIT_POSTS_PER_SUB,
        "restrict_sr": "1",  # limit results to this subreddit
    }

    try:
        response = client.get(url, params=params)
        if response.status_code == 429:
            logger.warning(f"[reddit] Rate limited on r/{subreddit} — skipping")
            return []
        if response.status_code != 200:
            logger.warning(
                f"[reddit] r/{subreddit} returned HTTP {response.status_code}"
            )
            return []

        data = response.json()
        children = data.get("data", {}).get("children", [])

        posts: list[dict[str, Any]] = []
        for child in children:
            pd = child.get("data", {})
            posts.append(
                {
                    "id": pd.get("id", ""),
                    "title": pd.get("title", ""),
                    "body": (pd.get("selftext") or "").strip(),
                    "score": int(pd.get("score") or 0),
                    "num_comments": int(pd.get("num_comments") or 0),
                    "created_utc": pd.get("created_utc"),
                    "subreddit": subreddit,
                    "url": f"https://www.reddit.com{pd.get('permalink', '')}",
                    "top_comments": [],  # populated after deduplication
                }
            )

        logger.debug(f"[reddit] r/{subreddit}: {len(posts)} posts for '{query}'")
        return posts

    except httpx.RequestError as exc:
        logger.warning(f"[reddit] Request error for r/{subreddit}: {exc}")
        return []
    except Exception as exc:
        logger.warning(f"[reddit] Unexpected error for r/{subreddit}: {exc}")
        return []


def _fetch_top_comments(
    client: httpx.Client,
    subreddit: str,
    post_id: str,
) -> list[dict[str, Any]]:
    """Fetch the top N comments for a single Reddit post.

    Args:
        client: Shared httpx client with User-Agent header set.
        subreddit: Subreddit name without the r/ prefix.
        post_id: Reddit post ID (the short alphanumeric string).

    Returns:
        List of up to MAX_REDDIT_COMMENTS comment dicts.
        Each comment: {body, score}. Empty list on any error.
    """
    url = f"{REDDIT_BASE_URL}/r/{subreddit}/comments/{post_id}.json"
    params = {"limit": MAX_REDDIT_COMMENTS, "sort": "top", "depth": "1"}

    try:
        response = client.get(url, params=params)
        if response.status_code != 200:
            return []

        data = response.json()
        # Response is a two-element list: [post_data, comments_data]
        if not isinstance(data, list) or len(data) < 2:
            return []

        children = data[1].get("data", {}).get("children", [])
        comments: list[dict[str, Any]] = []
        for child in children:
            cd = child.get("data", {})
            body = (cd.get("body") or "").strip()
            # Skip deleted/removed comments and the "load more" sentinel
            if body and body not in ("[deleted]", "[removed]"):
                comments.append(
                    {
                        "body": body,
                        "score": int(cd.get("score") or 0),
                    }
                )
            if len(comments) >= MAX_REDDIT_COMMENTS:
                break

        return comments

    except Exception as exc:
        logger.debug(f"[reddit] Could not fetch comments for {post_id}: {exc}")
        return []


def _compute_stats(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over the deduplicated post list.

    Args:
        posts: List of post dicts after deduplication and sorting.

    Returns:
        Dict with total_posts, avg_score, total_comments,
        subreddit_breakdown (dict mapping subreddit → post count).
    """
    if not posts:
        return {
            "total_posts": 0,
            "avg_score": 0,
            "total_comments": 0,
            "subreddit_breakdown": {},
        }

    total_score = sum(p["score"] for p in posts)
    total_comments = sum(p["num_comments"] for p in posts)
    breakdown: dict[str, int] = {}
    for post in posts:
        sub = post["subreddit"]
        breakdown[sub] = breakdown.get(sub, 0) + 1

    return {
        "total_posts": len(posts),
        "avg_score": round(total_score / len(posts), 1),
        "total_comments": total_comments,
        "subreddit_breakdown": breakdown,
    }


def _days_to_time_filter(days: int) -> str:
    """Convert a number of days to a Reddit API time_filter string.

    Args:
        days: Look-back window in days.

    Returns:
        One of "day", "week", "month", or "year".
    """
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    return "year"
