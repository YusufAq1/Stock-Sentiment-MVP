# AI Stock Research

A personal equity research CLI tool. Run one command and get a comprehensive sentiment analysis and research brief for any stock — aggregating financial news, Reddit discussion, SEC filings, earnings data, and price action, all synthesized by Claude.

```
python analyze.py AAPL
```

---

## What it does

For any given ticker the tool:

1. Fetches the last 30 days of price/OHLCV data and key stats (yfinance)
2. Pulls recent news articles from Finnhub and NewsAPI
3. Searches Reddit (`r/wallstreetbets`, `r/stocks`, `r/investing`, `r/options`) via the public JSON API — no credentials needed
4. Retrieves recent SEC filings (10-K, 10-Q, 8-K) from EDGAR
5. Gets upcoming earnings date and recent EPS beat/miss history
6. Sends everything to Claude in a single API call
7. Outputs a structured research brief to your terminal and saves an HTML report

The HTML report auto-opens in your browser after each run.

Works with both **US tickers** (`AAPL`, `NVDA`, `TSLA`) and **TSX tickers** (`SHOP.TO`, `RY.TO`, `BNS.TO`). TSX stocks will have no SEC filings and may have sparser news coverage — the tool notes data gaps and adjusts its confidence accordingly.

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd ai-stock-research

python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
FINNHUB_API_KEY=your_finnhub_key
NEWS_API_KEY=your_newsapi_key
EDGAR_USER_AGENT=stock-sentiment-engine/1.0 your@email.com
```

Where to get each key:

| Key | Source | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | Pay-per-use (~$0.01–0.05/run) |
| `FINNHUB_API_KEY` | [finnhub.io](https://finnhub.io) → Sign up | Free tier (60 req/min) |
| `NEWS_API_KEY` | [newsapi.org](https://newsapi.org) → Register | Free tier (100 req/day) |
| `EDGAR_USER_AGENT` | No signup — just a contact string | Free |

Reddit requires **no credentials** — data is fetched via the public JSON API.

---

## Usage

```bash
# Analyze a US stock
python analyze.py AAPL

# Analyze a TSX stock
python analyze.py SHOP.TO

# Force fresh data (skip cache)
python analyze.py AAPL --no-cache

# Only print to terminal, skip the HTML report
python analyze.py AAPL --terminal-only

# Look back 7 days instead of the default 14
python analyze.py AAPL --days 7

# Show verbose/debug logging
python analyze.py AAPL -v

# Save reports to a custom directory
python analyze.py AAPL --output-dir ~/my-reports
```

### All options

| Argument | Default | Description |
|---|---|---|
| `ticker` | required | Stock ticker symbol |
| `--no-cache` | off | Ignore cached data, re-fetch everything |
| `--terminal-only` | off | Skip HTML report generation |
| `--output-dir` | `./reports` | Where to save HTML reports |
| `--days` | `14` | Days of historical news/Reddit data to fetch |
| `-v`, `--verbose` | off | Show debug logs |

---

## Output

### Terminal

A colour-coded report rendered with `rich`:

```
────────────── AAPL — Apple Inc.    2026-02-24 ──────────────

 PRICE SNAPSHOT
 ┌──────────────────┬────────────────┬───────────┬──────────┐
 │ $223.45  +1.2%   │ 52W: $164–$237 │ P/E: 29.1x│ MCap:3.4T│
 └──────────────────┴────────────────┴───────────┴──────────┘

 SENTIMENT GAUGE
  Overall    ████████░░  +0.58  Bullish  Confidence: 74%
  News       ███████░░░  +0.45
  Reddit     █████████░  +0.72  Mood: FOMO

 BULL CASE                          BEAR CASE
 • Strong iPhone 17 pre-order...    • Valuation stretched at 29x...
 • Services revenue accelerating    • China revenue headwinds...
 • Cash return programme...         • AI spend pressure on margins...

 VERDICT
 Data points to cautious optimism heading into the next
 earnings cycle...
```

### HTML Report

A self-contained dark-themed HTML file saved to `reports/AAPL_2026-02-24.html` and auto-opened in your browser. Includes all sections from the terminal output plus the full OHLCV table.

---

## Caching

Fetched data is cached as JSON files in `cache/` with a 4-hour TTL. Re-running the same ticker within 4 hours reuses cached data and only re-runs the Claude analysis. Use `--no-cache` to force a full refresh.

Cache files are named `{TICKER}_{fetcher}_{YYYY-MM-DD}.json` and are gitignored.

---

## Cost

A typical run costs roughly **$0.01–0.05** in Anthropic API fees depending on how much data is available for the ticker. The model used is `claude-sonnet-4-5-20250929`.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Invalid or unrecognised ticker |
| `2` | Missing or invalid API keys in `.env` |
| `3` | All data fetchers failed |
| `4` | Claude API call failed after retries |

---

## Project structure

```
├── analyze.py          # CLI entry point
├── config.py           # Environment loading, constants
├── cache.py            # File-based JSON cache utility
├── fetchers/
│   ├── price.py        # yfinance — price, stats, OHLCV
│   ├── news.py         # Finnhub + NewsAPI
│   ├── reddit.py       # Reddit public JSON API (no auth)
│   ├── sec.py          # SEC EDGAR filings
│   └── earnings.py     # yfinance earnings data
├── analysis/
│   ├── formatter.py    # Builds the LLM context bundle
│   └── llm.py          # Claude API call + JSON parsing
├── output/
│   ├── terminal.py     # Rich terminal rendering
│   └── html.py         # Jinja2 HTML report + browser open
├── templates/
│   └── report.html     # Self-contained HTML template
├── cache/              # Auto-created, gitignored
└── reports/            # Auto-created, gitignored
```

---

## Disclaimer

This tool is for **research purposes only**. It does not provide financial advice. Always do your own due diligence before making investment decisions.