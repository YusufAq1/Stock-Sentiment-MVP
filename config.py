"""Central configuration module for the Stock Sentiment Engine.

Loads environment variables from .env, validates required keys,
defines all project-wide constants, and provides logging setup.
Every other module imports constants and AppConfig from here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# ─── Project Root ─────────────────────────────────────────────────────────────
ROOT_DIR: Path = Path(__file__).parent.resolve()

# ─── Runtime Directories ──────────────────────────────────────────────────────
CACHE_DIR: Path = ROOT_DIR / "cache"
REPORTS_DIR: Path = ROOT_DIR / "reports"

# ─── Cache Settings ───────────────────────────────────────────────────────────
CACHE_TTL_HOURS: int = 4

# ─── Fetcher Limits ───────────────────────────────────────────────────────────
MAX_ARTICLES: int = 50
MAX_REDDIT_POSTS: int = 30
MAX_REDDIT_COMMENTS: int = 3
REDDIT_POSTS_PER_SUB: int = 15
DEFAULT_DAYS: int = 14

# ─── Subreddits ───────────────────────────────────────────────────────────────
SUBREDDITS: list[str] = ["wallstreetbets", "stocks", "investing", "options"]

# ─── LLM Settings ─────────────────────────────────────────────────────────────
LLM_MODEL: str = "claude-sonnet-4-5-20250929"
LLM_MAX_TOKENS: int = 4096
LLM_MAX_RETRIES: int = 3
LLM_RETRY_BASE_SECONDS: float = 1.0  # backoff: 1s, 2s, 4s

# ─── Context Budget ───────────────────────────────────────────────────────────
MAX_CONTEXT_TOKENS: int = 80_000  # Soft cap for formatter truncation

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# ─── External API Base URLs ───────────────────────────────────────────────────
FINNHUB_BASE_URL: str = "https://finnhub.io/api/v1"
NEWSAPI_BASE_URL: str = "https://newsapi.org/v2"
EDGAR_SUBMISSIONS_URL: str = "https://data.sec.gov/submissions"
EDGAR_SEARCH_URL: str = "https://efts.sec.gov/LATEST/search-index"


# ─── AppConfig ────────────────────────────────────────────────────────────────

class AppConfig:
    """Holds all validated runtime configuration loaded from the environment.

    Attributes:
        anthropic_api_key: Anthropic API key for Claude.
        finnhub_api_key: Finnhub market data API key.
        news_api_key: NewsAPI key.
        reddit_client_id: Reddit OAuth client ID.
        reddit_client_secret: Reddit OAuth client secret.
        reddit_user_agent: Reddit API user agent string.
        edgar_user_agent: SEC EDGAR User-Agent header value.
    """

    def __init__(
        self,
        anthropic_api_key: str,
        finnhub_api_key: str,
        news_api_key: str,
        reddit_client_id: str,
        reddit_client_secret: str,
        reddit_user_agent: str,
        edgar_user_agent: str,
    ) -> None:
        self.anthropic_api_key = anthropic_api_key
        self.finnhub_api_key = finnhub_api_key
        self.news_api_key = news_api_key
        self.reddit_client_id = reddit_client_id
        self.reddit_client_secret = reddit_client_secret
        self.reddit_user_agent = reddit_user_agent
        self.edgar_user_agent = edgar_user_agent


def load_config() -> AppConfig:
    """Load and validate all required environment variables from .env.

    Loads the .env file from the project root and checks that every
    required key is present and non-empty. Raises SystemExit with
    exit code 2 and a human-readable message listing all missing keys
    so the user knows exactly what to fix.

    Returns:
        AppConfig: Validated configuration object.

    Raises:
        SystemExit: With exit code 2 if any required env var is missing.
    """
    load_dotenv(ROOT_DIR / ".env")

    required: dict[str, str] = {
        "ANTHROPIC_API_KEY": "Anthropic API key (https://console.anthropic.com)",
        "FINNHUB_API_KEY": "Finnhub API key (https://finnhub.io)",
        "NEWS_API_KEY": "NewsAPI key (https://newsapi.org)",
        "REDDIT_CLIENT_ID": "Reddit client ID (https://www.reddit.com/prefs/apps)",
        "REDDIT_CLIENT_SECRET": "Reddit client secret",
        "EDGAR_USER_AGENT": (
            "EDGAR User-Agent string (e.g. 'stock-sentiment-engine/1.0 you@example.com')"
        ),
    }

    missing: list[str] = []
    for key, description in required.items():
        if not os.getenv(key, "").strip():
            missing.append(f"  {key} — {description}")

    if missing:
        lines = "\n".join(missing)
        print(
            f"[ERROR] Missing required environment variables. "
            f"Copy .env.example to .env and fill in:\n{lines}"
        )
        raise SystemExit(2)

    # REDDIT_USER_AGENT is optional — hardcoded default if not set
    reddit_user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "stock-sentiment-engine/1.0 by u/yourusername",
    ).strip()

    return AppConfig(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        finnhub_api_key=os.environ["FINNHUB_API_KEY"],
        news_api_key=os.environ["NEWS_API_KEY"],
        reddit_client_id=os.environ["REDDIT_CLIENT_ID"],
        reddit_client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        reddit_user_agent=reddit_user_agent,
        edgar_user_agent=os.environ["EDGAR_USER_AGENT"],
    )


def setup_logging(verbose: bool = False) -> None:
    """Configure the root logger for the application.

    Should be called once at startup from analyze.py before any
    fetchers or analysis modules run. Individual modules obtain
    their loggers via logging.getLogger(__name__).

    Args:
        verbose: If True, set log level to DEBUG. Otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
