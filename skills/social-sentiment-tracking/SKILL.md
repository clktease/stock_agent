# Social Sentiment Tracking Skill

## Overview
Tracks statements/coverage of specific public figures (executives, fund managers,
politicians, influencers) via web search and turns genuinely new coverage into
investment-relevant alerts, delegating to specialist sub-agents when a clear
ticker/asset link exists. Distinguishes confirmed quotes from media interpretation
and always flags single-statement noise/manipulation risk (e.g. meme-stock
dynamics). Background monitoring runs automatically once someone is tracked —
this skill does not require the user to manually re-check.

## Available Tools

### `track_influencer`
Adds a public figure to the persistent background-monitoring watchlist.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `name` | Full name, e.g. `"Elon Musk"` | required |
| `aliases` | Alternate names/handles, e.g. `["@elonmusk"]` | `[]` |
| `context_tickers` | Tickers commonly associated with this person, e.g. `["TSLA"]` | `[]` |

**Note**: the first background check only establishes a baseline — it will not
generate an alert. Only genuinely new content found on later checks triggers
a notification. Tell the user this explicitly so silence isn't mistaken for failure.

---

### `untrack_influencer`
Removes a public figure from the watchlist.

| Parameter | Values | Default |
|-----------|--------|---------|
| `name` | Name (or alias) as previously tracked | required |

---

### `list_tracked_influencers`
Lists everyone currently tracked, including last-checked time and alert count.
No parameters.

---

### `get_recent_statements`
On-demand search for recent statements/coverage of ANY public figure — does
not require the person to be on the watchlist. Use this for one-off questions
like "what has Elon Musk said about Tesla this week?".

| Parameter | Values | Default |
|-----------|--------|---------|
| `name` | Any person's name | required |

## Standard Workflows

### A. User asks to start tracking someone
1. Call `track_influencer(name, aliases, context_tickers)`.
2. Confirm what will be monitored and mention the baseline-only first check
   (background poll cycle runs automatically, default ~30 min cadence).

### B. On-demand "what has X said" query
1. Call `get_recent_statements(name)`.
2. Separate confirmed direct quotes from media paraphrase/speculation.
3. If a clear ticker/asset link exists, delegate to the relevant sub-agent
   (technical-analyst / fundamental-analyst / portfolio-manager) for deeper analysis.
4. If no clear investment relevance, say so explicitly — do not force a rating.
5. Always add the noise/manipulation disclaimer (see Output Format).

### C. Background alert synthesis (system-triggered)
Same reasoning as workflow B, but triggered automatically by the background
poll cycle rather than a user query. The response is pushed to the user via
a live notification instead of returned directly in a chat turn.

## Output Format

```
## 🗣️ {Person Name} — Recent Statement Alert

### What Was Said
[Confirmed direct quotes vs. media interpretation, with source links]

### Investment Relevance
- Related ticker(s)/asset(s): {tickers, or "None identified"}
- Potential impact: {direction + rationale, or "No clear investment relevance"}
- Confidence: High / Medium / Low

### ⚠️ Risk & Noise Disclaimer
Single-statement-driven signals can be noisy, unverified, or manipulated
(e.g. meme-stock dynamics, pump-and-dump risk). This is not a formal
recommendation — verify before acting.
```

## Global Market Environment Briefing

For "what's the overall market environment/mood right now?" style requests
(daily/weekly briefings, risk-on/risk-off checks, pre-trade context), use
`search_news` to collect current readings rather than relying on stale
knowledge:

1. Search for major indices (S&P 500, NASDAQ, Dow, Nikkei 225, key European
   indices), USD/JPY and major FX pairs, WTI crude, Gold, US 2Y/10Y Treasury
   yields, and VIX.
2. Classify: trend direction (up/down/range), risk sentiment (risk-on vs
   risk-off), volatility regime from VIX (<15 calm, 15-20 normal, 20-30
   elevated, >30 stressed).
3. Note upcoming high-impact events (FOMC, CPI, NFP, GDP) and rank by
   importance (⭐⭐⭐ critical / ⭐⭐ important / ⭐ reference).
4. Cross-check quantitative context from `get_market_breadth` /
   `assess_market_risk` (macro-research skill) rather than relying on
   narrative alone.
5. Summarize as a short "Market Summary" block (indices + FX + VIX + key
   events + one-line environment call), then expand into detail sections
   (US/Asia/Europe, FX & commodities, risk factors) only if the user wants
   more depth.

## Trending Theme Detection (lightweight)

For "what market themes are trending?" / "which sectors are hot/cold?"
requests, this is a narrower adaptation of a heavier FINVIZ-industry-scan
skill — it leans on tools already available here rather than a new scraper:

1. Call `get_market_breadth` (macro-research skill) and read its
   `sector_summary` block for quantitative uptrend/downtrend/overbought/
   oversold sectors — this is the "heat" signal.
2. For the top 2-3 hottest and coldest sectors, use `search_news` with
   queries like `"[sector/theme] stocks momentum [month] [year]"` to confirm
   whether the narrative is strengthening, fading, or absent.
3. Combine into a confidence call: quantitative hot + strong narrative =
   High confidence; quantitative hot + weak/no narrative = Medium
   (momentum may be fading or narrative lagging price); quantitative cold +
   strong narrative = Medium (narrative may lead price); neither = Low.
4. Flag crowded-trade risk qualitatively (heavy recent media coverage, many
   new thematic ETFs/products launched) rather than computing an ETF-count
   score — note this is a judgment call, not a hard number.
5. Always caveat: this is momentum detection, not fundamental value — past
   thematic strength doesn't guarantee continuation.
