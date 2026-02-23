# Stock Sentiment Engine (MVP) — CLAUDE.md

## Project Overview

This is a **CLI-based Stock Research & Sentiment Engine** — a personal equity research tool that, with a single command, aggregates financial news, Reddit chatter, SEC filings, earnings data, and price action for any given ticker, then uses Claude to produce a comprehensive sentiment analysis and investment research brief.

The user is a Canadian investor who uses **Wealthsimple** and trades individual stocks across multiple strategies (long-term holds, swing trades, and active trading). The tool helps them make better-informed investment decisions by providing an information edge through faster, deeper analysis of publicly available data.

This is NOT a trading bot. It does NOT execute trades. It is a **research and analysis tool**.

### What It Does In One Sentence

You run `python analyze.py AAPL`, it fetches all available data, sends it to Claude for analysis, and outputs a full research brief to your terminal, a Markdown file, and an HTML report.

## Tech Stack

- **Language**: Python 3.11+
- **CLI**: argparse (built-in) for command-line argument parsing
- **LLM**: Anthropic Claude API (`claude-sonnet-4-5-20250929` for analysis)
- **Market Data**: `yfinance` for price data + earnings info
- **News Sources**: Finnhub News API, NewsAPI
- **Social Sentiment**: Reddit via PRAW (`r/wallstreetbets`, `r/stocks`, `r/investing`, `r/options`)
- **SEC Filings**: SEC EDGAR API (free, no key required)
- **HTTP Client**: `httpx` for all external API calls (async-capable, but used synchronously in MVP for simplicity)
- **Terminal Output**: `rich` library for colored, formatted terminal display
- **HTML Templating**: `jinja2` for HTML report generation
- **Environment Management**: `python-dotenv` for `.env` loading
- **Caching**: File-based JSON cache in `cache/` directory

### Key Tech Decisions

- **No database** — all data is ephemeral or file-cached. This is a CLI tool, not a server.
- **No async** — keep it simple. Synchronous Python with `httpx` (sync client) and PRAW. Fetchers run sequentially or with `concurrent.futures.ThreadPoolExecutor` for parallelism where beneficial.
- **No web framework** — no FastAPI, no Flask, no Streamlit. Just a Python script you run from the terminal.
- **Single Claude API call** — all fetched data is bundled into one structured prompt and sent in a single call to Claude. This is cheaper and produces better holistic analysis than per-article scoring.

## Project Structure

```
stock-sentiment-engine/
├── CLAUDE.md                   # This file — project spec for Claude Code
├── README.md                   # User-facing docs: setup, usage, examples
├── requirements.txt            # Python dependencies
├── .env                        # API keys — NEVER commit this
├── .env.example                # Template showing required env vars
├── .gitignore                  # Ignores .env, cache/, __pycache__, etc.
├── analyze.py                  # Entry point — CLI interface
├── config.py                   # Loads .env, validates all settings
├── fetchers/                   # Data fetching from external sources
│   ├── __init__.py
│   ├── news.py                 # Finnhub + NewsAPI article fetching
│   ├── reddit.py               # PRAW — search across 4 subreddits
│   ├── sec.py                  # SEC EDGAR — recent filings (10-K, 10-Q, 8-K)
│   ├── price.py                # yfinance — OHLCV, current price, key stats
│   └── earnings.py             # yfinance — next earnings date, recent surprise
├── analysis/
│   ├── __init__.py
│   ├── llm.py                  # Claude API call — builds prompt, parses response
│   └── formatter.py            # Structures raw fetched data into the LLM context bundle
├── output/
│   ├── __init__.py
│   ├── terminal.py             # Rich terminal output — colored panels, tables, gauges
│   ├── markdown.py             # Generates .md report file
│   └── html.py                 # Generates .html report file using Jinja2 template
├── cache/                      # Auto-created, gitignored — file-based JSON cache
├── reports/                    # Auto-created, gitignored — output reports land here
├── templates/
│   └── report.html             # Jinja2 HTML template for the styled report
└── tests/
    ├── __init__.py
    ├── conftest.py             # Shared fixtures, mock API responses
    ├── test_fetchers.py        # Tests for each fetcher (mocked API calls)
    ├── test_formatter.py       # Tests for data formatting/bundling
    └── test_output.py          # Tests for report generation
```

## Environment Variables Required

```
# LLM — Required
ANTHROPIC_API_KEY=sk-ant-api03-...

# Market Data & News — Required
FINNHUB_API_KEY=...
NEWS_API_KEY=...

# Reddit — Required
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=stock-sentiment-engine/1.0 by u/yourusername
```

Create a `.env.example` file with all keys shown as empty placeholders and comments explaining where to get each one:
- Anthropic: https://console.anthropic.com → API Keys
- Finnhub: https://finnhub.io → Free API key
- NewsAPI: https://newsapi.org → Register for free key
- Reddit: https://www.reddit.com/prefs/apps → Create "script" type app

## CLI Interface

### Basic Usage

```bash
# Analyze a US stock
python analyze.py AAPL

# Analyze a TSX stock (Canadian)
python analyze.py SHOP.TO

# Skip cache and force fresh data fetch
python analyze.py AAPL --no-cache

# Output only to terminal (skip file reports)
python analyze.py AAPL --terminal-only

# Specify a custom report output directory
python analyze.py AAPL --output-dir ./my-reports

# Verbose mode — show fetcher progress and debug info
python analyze.py AAPL -v
```

### CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `ticker` | positional | required | Stock ticker symbol (e.g., `AAPL`, `SHOP.TO`, `RY.TO`) |
| `--no-cache` | flag | `False` | Force fresh data fetch, ignore cache |
| `--terminal-only` | flag | `False` | Only print to terminal, don't generate report files |
| `--output-dir` | string | `./reports` | Directory for saving report files |
| `-v`, `--verbose` | flag | `False` | Show detailed progress and debug logging |
| `--days` | int | `14` | Number of days of historical news/data to fetch |

### Exit Codes

- `0` — Success
- `1` — Invalid ticker or ticker not found
- `2` — Missing or invalid API keys
- `3` — All fetchers failed (no data to analyze)
- `4` — Claude API call failed

## Pipeline Architecture

The script executes a linear 5-step pipeline:

### Step 1: Validate & Setup

- Parse CLI arguments
- Load and validate `.env` configuration (fail fast if keys are missing)
- Validate the ticker symbol using yfinance (check that it resolves to a real security)
- Create `cache/` and `reports/` directories if they don't exist
- Check cache for existing recent data (within TTL)

### Step 2: Fetch Data (parallel where beneficial)

Use `concurrent.futures.ThreadPoolExecutor` to run fetchers in parallel where possible. Each fetcher is independent and should never crash the pipeline — if one fails, log the error and continue with the data from the others.

**Price Fetcher** (`fetchers/price.py`):
- Use `yfinance.Ticker(symbol)` to get:
  - Last 30 days of daily OHLCV data
  - Current price, previous close, day change ($ and %)
  - 52-week high and low
  - Market cap
  - Average volume (10-day and 3-month)
  - P/E ratio (trailing and forward), EPS
  - Dividend yield (if applicable)
  - Beta
  - Sector and industry
  - Currency (USD or CAD) — important for TSX tickers
- Return as a structured dict
- yfinance handles both US tickers (`AAPL`) and TSX tickers (`SHOP.TO`) natively — no special handling needed other than noting the currency

**News Fetcher** (`fetchers/news.py`):
- **Finnhub**: Use `GET /company-news?symbol={ticker}&from={start}&to={end}` to fetch news articles from the last `--days` days
  - Extract: headline, summary, source, url, datetime, category
  - Finnhub free tier rate limit: 60 calls/min — unlikely to hit with single ticker, but add a simple rate limiter anyway
  - For TSX tickers, strip the `.TO` suffix when querying Finnhub (Finnhub uses plain symbols)
- **NewsAPI**: Use `GET /everything?q={company_name OR ticker}&from={start}&sortBy=relevancy&language=en`
  - Extract: title, description, source name, url, publishedAt
  - NewsAPI free tier: 100 requests/day — be conservative
  - Use the company name (from yfinance info) as the primary search query, ticker symbol as secondary
- Combine and deduplicate articles from both sources by URL
- Sort by date descending (most recent first)
- Cap at 50 articles maximum to keep the LLM context manageable
- Return as a list of article dicts

**Reddit Fetcher** (`fetchers/reddit.py`):
- Initialize PRAW in **read-only mode** (no username/password needed, just client_id, client_secret, user_agent)
- Search each of these subreddits for the ticker symbol: `wallstreetbets`, `stocks`, `investing`, `options`
- For each subreddit:
  - Use `subreddit.search(ticker, sort="relevance", time_filter="month", limit=15)` to find relevant posts
  - For each post, extract: title, selftext (body), score, num_comments, created_utc, subreddit name, url
  - Also fetch the top 3 comments (by score) from each post for additional sentiment context: comment body, score
- Deduplicate posts by ID across subreddits (a post can appear in search results for multiple subs)
- Sort by score descending (most popular first)
- Cap at 30 posts maximum
- Calculate basic stats: total mentions, average post score, total comments across all posts, subreddit breakdown
- Return as a structured dict with both the posts list and summary stats

**SEC Fetcher** (`fetchers/sec.py`):
- Use the SEC EDGAR full-text search API (free, no key needed): `GET https://efts.sec.gov/LATEST/search-index?q={ticker}&dateRange=custom&startdt={start}&enddt={end}&forms=10-K,10-Q,8-K`
- Alternative: Use EDGAR company search `GET https://data.sec.gov/submissions/CIK{cik}.json` to get recent filings
- For each filing found:
  - Extract: form type (10-K, 10-Q, 8-K), filing date, description, URL to the filing document
  - For 8-K filings (material events): attempt to fetch and extract the plain-text content (these are usually short and contain important event disclosures)
  - For 10-K/10-Q: just note that they exist with filing date and description — full text is too long for the MVP prompt
- **TSX tickers will have NO SEC filings** — this is expected. The fetcher should return an empty result gracefully with a note like "No SEC filings (non-US listed security)"
- EDGAR requires a `User-Agent` header with your name and email: `User-Agent: stock-sentiment-engine your@email.com`
- Return as a list of filing dicts

**Earnings Fetcher** (`fetchers/earnings.py`):
- Use `yfinance.Ticker(symbol)` to get:
  - Next earnings date (`.calendar`)
  - Most recent earnings: EPS estimate vs actual, revenue estimate vs actual, surprise % (`.earnings_history` or `.quarterly_earnings`)
  - Earnings trend data if available
- Calculate how many days until next earnings
- Note whether the stock beat or missed on the most recent quarter
- Return as a structured dict

### Step 3: Format Data for LLM

**Formatter** (`analysis/formatter.py`):
- Takes all the raw data from the fetchers and structures it into a clean, well-organized text bundle that becomes the user message to Claude
- The bundle should be structured with clear sections and XML-style tags for Claude to parse easily:

```
<ticker_info>
Symbol: AAPL
Company: Apple Inc.
Sector: Technology
Current Price: $241.53 (+1.2%)
... (key stats)
</ticker_info>

<price_data>
Last 30 days OHLCV summary...
Recent trend description...
Key support/resistance levels...
</price_data>

<news_articles count="23">
<article source="Reuters" date="2026-02-21">
Headline: ...
Summary: ...
</article>
... (all articles)
</news_articles>

<reddit_posts count="47" subreddits="wallstreetbets,stocks,investing,options">
<summary>
Total mentions: 47
Average post score: 234
Most active subreddit: wallstreetbets (28 posts)
</summary>
<post subreddit="wallstreetbets" score="1523" comments="342" date="2026-02-21">
Title: ...
Body: ...
Top comments: ...
</post>
... (all posts)
</reddit_posts>

<sec_filings count="2">
<filing type="8-K" date="2026-02-15">
Description: ...
Content: ... (if available)
</filing>
</sec_filings>

<earnings>
Next earnings date: April 30, 2026 (67 days away)
Last quarter: Beat EPS by 5.2%, Beat revenue by 2.1%
</earnings>
```

- Truncate individual articles/posts if the total bundle would exceed ~80,000 tokens. Prioritize: most recent content, highest-scored Reddit posts, 8-K filing content. Trim older or lower-relevance items first.
- Include a count of items that were truncated so Claude knows data was trimmed

### Step 4: LLM Analysis

**LLM Module** (`analysis/llm.py`):
- Use the `anthropic` Python SDK
- Model: `claude-sonnet-4-5-20250929` (fast, cheap, good enough for this analysis)
- Single API call with a system prompt and user message

**System Prompt** (this is critical — get this right):
```
You are a senior equity research analyst producing a comprehensive research brief for a stock ticker. You have been given real-time data including news articles, Reddit discussions, SEC filings, earnings data, and price action.

Your job is to synthesize ALL of this data into an actionable research brief. Be specific — cite particular articles, Reddit posts, or filings when making claims. Do not be generic.

You must respond with a JSON object matching this exact schema:

{
  "overall_sentiment": {
    "score": <float from -1.0 (very bearish) to 1.0 (very bullish)>,
    "label": <"Very Bearish" | "Bearish" | "Slightly Bearish" | "Neutral" | "Slightly Bullish" | "Bullish" | "Very Bullish">,
    "confidence": <float from 0.0 to 1.0 — how confident you are in this assessment given the available data>
  },
  "news_sentiment": {
    "score": <float -1.0 to 1.0>,
    "summary": <string — 3-5 sentence summary of the key themes from news coverage>,
    "key_articles": [<list of 3-5 strings, each a one-sentence summary of the most impactful articles>]
  },
  "reddit_sentiment": {
    "score": <float -1.0 to 1.0>,
    "mood": <"FOMO" | "Fear" | "Euphoria" | "Anxiety" | "Indifferent" | "Divided" | "Cautiously Optimistic" | "Cautiously Pessimistic">,
    "summary": <string — 2-3 sentence summary of what retail traders are saying>,
    "notable_posts": [<list of 2-3 strings, each summarizing a notable Reddit post or viewpoint>]
  },
  "sec_filings": {
    "has_recent_filings": <boolean>,
    "summary": <string — summary of any notable recent filings, or "No recent SEC filings" / "Not applicable (non-US listed)">,
    "red_flags": [<list of strings — any concerning items from filings, empty list if none>]
  },
  "earnings": {
    "summary": <string — earnings context: recent performance, next date, expectations>,
    "beat_or_miss": <"Beat" | "Miss" | "In-line" | "N/A">,
    "days_until_next": <int or null>
  },
  "bull_case": [<list of 3-5 strings — the strongest bullish arguments based on the data>],
  "bear_case": [<list of 3-5 strings — the strongest bearish arguments based on the data>],
  "discrepancies": [<list of strings — any notable divergences: news vs reddit sentiment, price vs sentiment, insider actions vs public narrative, etc. Empty list if none>],
  "key_signals": [<list of strings — upcoming catalysts, events, dates, or patterns to watch>],
  "technical_snapshot": <string — brief technical analysis based on the price data: trend direction, support/resistance, volume patterns, notable moving average positions>,
  "verdict": <string — 3-5 sentence plain-English verdict summarizing the overall picture and what an investor should pay attention to. Do NOT give buy/sell advice. Frame as "here's what the data suggests" and "here's what to watch for.">,
  "data_quality": {
    "news_count": <int — number of articles analyzed>,
    "reddit_count": <int — number of Reddit posts analyzed>,
    "filing_count": <int — number of SEC filings found>,
    "data_gaps": [<list of strings — any notable gaps: "Low news coverage", "No SEC filings", "Limited Reddit discussion", etc.>],
    "confidence_note": <string — if data is sparse, explain how that affects confidence>
  }
}

Important rules:
- Be SPECIFIC. Reference actual articles, posts, and data points. Don't be vague.
- Be HONEST about uncertainty. If data is sparse (especially for TSX/Canadian stocks), say so and lower your confidence.
- Do NOT give financial advice. Do not say "buy" or "sell". Frame everything as analysis, not recommendation.
- If news and Reddit sentiment disagree, call it out explicitly in discrepancies.
- If price action contradicts sentiment (e.g., price rising but sentiment is bearish), flag it.
- Consider recency — weight very recent information more heavily.
- For the verdict, be direct and opinionated about what the data shows, but always note caveats.
```

**User Message**: The formatted data bundle from Step 3.

**Response Handling**:
- Parse Claude's JSON response using `json.loads()`
- If JSON parsing fails, try to extract JSON from the response (Claude sometimes wraps it in markdown code blocks) — strip ```json and ``` before parsing
- Validate that all required fields are present
- If the response is malformed after retries, fall back to displaying the raw text response
- Retry logic: up to 3 retries with exponential backoff (1s, 2s, 4s) on API errors (rate limits, server errors)

### Step 5: Output Generation

All three output formats are generated from the same parsed JSON analysis result.

**Terminal Output** (`output/terminal.py`):
- Use the `rich` library for beautiful terminal formatting
- Layout:
  ```
  ╔══════════════════════════════════════════════════════════════╗
  ║  📊 {TICKER} — {Company Name}              {Date}          ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  PRICE SNAPSHOT                                             ║
  ║  Price: ${price} ({change%})  |  Volume: {vol}              ║
  ║  52W: ${low} — ${high}  |  P/E: {pe}  |  Mkt Cap: {cap}   ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  SENTIMENT GAUGE                                            ║
  ║  Overall:  ████████░░  0.62 (Bullish)  Confidence: 78%     ║
  ║  News:     ██████░░░░  0.45                                 ║
  ║  Reddit:   █████████░  0.81                                 ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  🐂 BULL CASE                                               ║
  ║  • Point 1...                                               ║
  ║  • Point 2...                                               ║
  ║  • Point 3...                                               ║
  ║                                                             ║
  ║  🐻 BEAR CASE                                               ║
  ║  • Point 1...                                               ║
  ║  • Point 2...                                               ║
  ║  • Point 3...                                               ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  📰 NEWS SUMMARY (23 articles)                              ║
  ║  {news summary text}                                        ║
  ║                                                             ║
  ║  💬 REDDIT PULSE (47 posts) — Mood: FOMO                   ║
  ║  {reddit summary text}                                      ║
  ║                                                             ║
  ║  📋 SEC FILINGS                                             ║
  ║  {filings summary}                                          ║
  ║                                                             ║
  ║  📅 EARNINGS                                                ║
  ║  {earnings summary}                                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  ⚠️  DISCREPANCIES                                          ║
  ║  {any discrepancies found}                                  ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  🔑 KEY SIGNALS                                             ║
  ║  {catalysts and events to watch}                            ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  📊 TECHNICAL SNAPSHOT                                      ║
  ║  {technical analysis summary}                               ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  📝 VERDICT                                                 ║
  ║  {verdict text}                                             ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  ⚠️  DISCLAIMER: This is a research tool, not financial     ║
  ║  advice. Always do your own due diligence.                  ║
  ╚══════════════════════════════════════════════════════════════╝
  ```
- Use color coding for sentiment:
  - Score > 0.3: green
  - Score -0.3 to 0.3: yellow
  - Score < -0.3: red
- Use `rich.progress` to show fetcher progress during Step 2
- The sentiment gauge bar should be a visual bar using `rich` (█ and ░ characters)

**Markdown Report** (`output/markdown.py`):
- Generate a clean Markdown file with all the same information
- Include a YAML front matter block with metadata (ticker, date, sentiment score)
- Use proper Markdown headings, lists, bold, and horizontal rules
- Include a simple ASCII sentiment bar since Markdown doesn't support rich formatting
- Save to `reports/{TICKER}_{YYYY-MM-DD}.md`

**HTML Report** (`output/html.py`):
- Use Jinja2 to render the `templates/report.html` template
- The HTML report should be **self-contained** (inline CSS, no external dependencies) so it can be opened in any browser without a server
- Design: clean, modern, readable — dark background option is a nice touch
- Include color-coded sentiment gauges (CSS gradients from red to green)
- Include the disclaimer at the bottom
- Save to `reports/{TICKER}_{YYYY-MM-DD}.html`
- After saving, automatically open it in the default browser using `webbrowser.open()`

## Caching System

Simple file-based caching to avoid hammering APIs when re-running the same ticker:

- Cache directory: `cache/`
- Cache key format: `{TICKER}_{fetcher_name}_{YYYY-MM-DD}.json`
- Default TTL: 4 hours (configurable via constant in `config.py`)
- Each fetcher checks for a valid cache file before making API calls
- The `--no-cache` flag bypasses all cache reads (but still writes new cache files)
- Cache files store the raw fetched data as JSON (before LLM analysis) so re-analysis doesn't require re-fetching
- The LLM analysis result itself is NOT cached (you may want to re-analyze the same data with a different prompt or after a code change)

Cache implementation:
```python
# In each fetcher:
def fetch_news(ticker: str, days: int, use_cache: bool = True) -> dict:
    cache_file = get_cache_path(ticker, "news")
    if use_cache and cache_is_valid(cache_file, ttl_hours=4):
        return load_cache(cache_file)

    # ... fetch from APIs ...

    save_cache(cache_file, result)
    return result
```

## Error Handling Philosophy

**No single fetcher failure should crash the entire pipeline.**

- Each fetcher is wrapped in a try/except at the pipeline level
- If a fetcher fails, log the error (with stack trace in verbose mode) and continue
- The formatter handles missing data gracefully — if news came back empty, the LLM context bundle simply notes "No news articles were found for this period"
- The LLM is explicitly told about data gaps so it can adjust its confidence
- If ALL fetchers fail, exit with code 3 and a helpful error message
- If the Claude API call fails after retries, exit with code 4
- API key validation happens at startup (Step 1) — don't even try to fetch if keys are missing

Specific error handling per fetcher:
- **yfinance**: if the ticker symbol doesn't resolve, exit with code 1 immediately
- **Finnhub**: handle 429 (rate limit) with exponential backoff. Handle empty response for TSX tickers (Finnhub may not cover them — this is fine, not an error)
- **NewsAPI**: handle 429 and 401 (invalid key). Handle zero results gracefully.
- **PRAW**: handle `prawcore.exceptions.ResponseException` for auth failures. Handle zero search results gracefully.
- **EDGAR**: handle 404 and connection errors. TSX tickers will always return empty — handle gracefully with a note.

## Coding Standards & Conventions

- **Type hints** on every function signature — use `dict`, `list`, `str`, `int`, `float`, `bool`, `Optional`, `Any` from typing
- **Docstrings** on every public function and class (Google-style docstrings)
- **Logging**: use Python's `logging` module. Default level: `INFO`. Verbose mode (`-v`): `DEBUG`. Use a consistent format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- **No hardcoded API keys, URLs, or magic numbers** — everything configurable via `config.py` and `.env`
- **Constants** (like cache TTL, max articles, subreddit list) should be defined at the top of `config.py` as named constants, not buried in code
- **Error messages** should be helpful and actionable: "Finnhub API returned 401 — check that FINNHUB_API_KEY in .env is valid" not just "API error"
- **f-strings** for string formatting (not `.format()` or `%`)
- **Pathlib** (`pathlib.Path`) for all file path operations, not `os.path`
- **snake_case** for functions and variables, **PascalCase** for classes
- All timestamps handled as UTC `datetime` objects with timezone awareness
- Monetary values displayed with proper formatting: `$1,234.56`, `C$1,234.56`

## Important Constraints

### Rate Limits
- **Finnhub free tier**: 60 calls/min — not an issue for single ticker, but add basic awareness
- **NewsAPI free tier**: 100 requests/day — be conservative, one request per run is fine
- **Reddit API (PRAW)**: 100 calls/min — search + fetching comments for 4 subreddits should be well within this
- **Anthropic API**: depends on tier, but one call per run is minimal. Add retry with exponential backoff for 429s.
- **SEC EDGAR**: 10 requests/sec — add a `User-Agent` header as required

### Canadian Context
- Support TSX tickers (e.g., `RY.TO`, `SHOP.TO`, `BNS.TO`) alongside US tickers
- yfinance handles TSX tickers natively — just pass `SHOP.TO`
- TSX tickers will likely have: less news coverage (Finnhub may return nothing), no SEC filings (they file with SEDAR, not EDGAR), less Reddit discussion
- The tool should gracefully handle sparse data for TSX tickers — lower confidence, note the data gaps, still produce a useful report with whatever data is available
- Display currency correctly: USD for US stocks, CAD for TSX stocks (get from yfinance `info['currency']`)

### Cost Consciousness
- **One Claude API call per run** — the entire data bundle is analyzed in a single call
- Using `claude-sonnet-4-5-20250929` (not Opus) — much cheaper
- Cache raw data to avoid redundant API calls
- A typical run should cost ~$0.01-0.05 in Claude API fees depending on how much data is fetched

### No Financial Advice
- The tool includes a disclaimer in every output format
- Claude's system prompt explicitly prohibits buy/sell recommendations
- Language should be analytical, not advisory: "the data suggests" not "you should"

## Dependencies (requirements.txt)

```
anthropic>=0.43.0
yfinance>=0.2.36
praw>=7.7.0
httpx>=0.27.0
rich>=13.7.0
jinja2>=3.1.0
python-dotenv>=1.0.0
```

## Build Order (Priority Sequence)

Build these in order. Each step should be fully functional and testable before moving to the next.

1. **Project scaffolding**: Create directory structure, `requirements.txt`, `.env.example`, `.gitignore`, `config.py` with environment loading and validation
2. **Price fetcher**: `fetchers/price.py` — fetch and structure price data via yfinance. Test with both US (`AAPL`) and TSX (`SHOP.TO`) tickers.
3. **News fetcher**: `fetchers/news.py` — Finnhub + NewsAPI integration with deduplication. Test with a high-coverage ticker like `AAPL`.
4. **Reddit fetcher**: `fetchers/reddit.py` — PRAW search across 4 subreddits. Test read-only mode.
5. **SEC fetcher**: `fetchers/sec.py` — EDGAR integration. Test with US ticker, verify TSX graceful empty result.
6. **Earnings fetcher**: `fetchers/earnings.py` — yfinance earnings data. Test with ticker that has upcoming earnings.
7. **Caching system**: Implement file-based cache in each fetcher.
8. **Formatter**: `analysis/formatter.py` — bundle all fetched data into structured LLM context.
9. **LLM analysis**: `analysis/llm.py` — Claude API call with system prompt, JSON response parsing, retry logic.
10. **Terminal output**: `output/terminal.py` — rich formatted terminal display.
11. **Markdown output**: `output/markdown.py` — generate .md report files.
12. **HTML output**: `output/html.py` + `templates/report.html` — styled HTML report with auto-open.
13. **CLI entry point**: `analyze.py` — wire everything together with argparse, progress display, error handling.
14. **Tests**: Write tests for fetchers (mocked), formatter, and output generation.
15. **README.md**: User-facing documentation with setup instructions, usage examples, and sample output.

## Future Enhancements (NOT in MVP — do not build these)

These are documented for future reference only. Do not implement any of these in the MVP:

- Database storage (PostgreSQL) for historical tracking
- Streamlit or web dashboard
- Scheduled/automated runs (APScheduler)
- Composite scoring system with time decay
- Narrative shift detection over time
- ML sentiment-return correlation model
- Alert system (email/webhook notifications)
- Multi-ticker batch analysis
- Deployment to Railway/Fly.io
- Watchlist management