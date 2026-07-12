# Macro Research Skill

## Overview
This skill combines **external API data** (via MCP) and **historical knowledge**
(via RAG) to provide macroeconomic context for stock analysis. Use it when asked
about interest rates, inflation, economic indicators, or when a stock analysis
needs broader market context beyond price and fundamentals.

## Available Tools

### MCP Tools (External API — Live Data)

#### `get_economic_indicators`
Fetches live macroeconomic data from FRED (Federal Reserve Economic Data) or
fallback sources. Returns interest rates, inflation, GDP, and employment data.

**When to use**: Questions about monetary policy, inflation trends, economic outlook.
- "What is the current Fed funds rate?"
- "What is the latest CPI reading?"
- "Is the economy in recession?"

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `indicators` | `"all"` or specific e.g. `"fed_rate,cpi"` | `"all"` |

---

#### `get_sec_filing_summary`
Retrieves the most recent 10-K or 10-Q filing metadata and risk factors from
SEC EDGAR (free, no API key required).

**When to use**: Questions about regulatory filings, management risk disclosures.
- "What are TSLA's main risk factors in its latest 10-K?"
- "When did AAPL file its most recent 10-Q?"

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `ticker` | e.g. `"AAPL"`, `"TSLA"` | required |
| `form_type` | `"10-K"`, `"10-Q"` | `"10-K"` |

---

#### `get_market_overview`
Snapshot of major indices (S&P 500, NASDAQ, DOW, VIX, Gold, Oil WTI) for today.

**When to use**: General market context at the start of any comprehensive analysis.

---

### RAG Tools (Knowledge Base — Historical Context)

#### `search_market_history`
Retrieves relevant passages from curated historical market event documents.

**When to use**: Questions that require historical analogy or crisis context.
- "Is the current tech valuation similar to the dot-com bubble?"
- "How did the market behave after the 2008 crisis?"
- "What caused the 2022 bear market and how long did it last?"

---

### Market Timing & Regime Tools (SKILL — no paid API required)

These four tools were adapted from community skills that originally targeted
FMP/FINVIZ Elite APIs, ported to run on free yfinance + TraderMonty CSV data
instead. Each documents its own simplifications in a `methodology_note` field
in its JSON output — read that field before presenting scores as precise.

#### `get_market_breadth`
How broadly the market rally/decline is participated in: S&P 500 breadth
(8-day vs 200-day MA), the US market uptrend stock ratio (~2,800 stocks, 11
sectors), and sector-level rotation (overbought/oversold, cyclical/defensive).
Returns a 0-100 composite health score + zone (Strong/Healthy/Neutral/
Weakening/Critical) + suggested equity exposure range. No parameters.

**When to use**: "is this rally broad-based?", "which sectors are leading?",
"is breadth deteriorating even though the index is at highs?"

If the user pastes in a breadth chart *image* (S&P 500 200MA breadth chart or
uptrend-ratio chart), read it directly with vision — the CSV data from this
tool is the authoritative numeric source; treat the image as supplementary
visual confirmation only, and prefer the CSV values if they conflict.

#### `get_market_timing_signals`
O'Neil-style Distribution Days (institutional selling accumulation — a
defensive/topping signal) and Follow-Through Days (rally confirmation after a
correction — an offensive/bottoming signal), for one or more index proxies.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `symbols` | Comma-separated, e.g. `"SPY,QQQ"` | `"SPY,QQQ"` |

**When to use**: after market close, before changing leveraged exposure,
"has the market bottomed?", "is this uptrend getting vulnerable?"

#### `get_macro_regime`
Structural (1-2 year) macro regime via cross-asset ETF ratios: market
concentration (RSP/SPY), size factor (IWM/SPY), credit conditions (HYG/LQD),
equity-bond relationship (SPY/TLT + correlation), sector rotation (XLY/XLP),
plus the 10Y-2Y yield curve when `FRED_API_KEY` is set. Classifies as
Concentration / Broadening / Contraction / Inflationary / Transitional.

**When to use**: long-term/structural positioning questions — NOT short-term
timing (use `get_market_timing_signals` or `get_market_breadth` for that).

#### `assess_market_risk`
Composite 0-100 market top/bubble-risk score blending Distribution Days,
breadth health, VIX complacency (6-month percentile), and defensive sector
rotation. Does **not** include Put/Call ratio or margin debt (no free API) —
its `missing_inputs_to_supplement_via_search` field lists what to look up via
`search_news` before finalizing a "top is forming" call.

**When to use**: "is the market topping?", "should I take profits?", "is this
a bubble?"

---

## Standard Workflows

### A. Macro context for a stock analysis
1. Call `get_market_overview()` → broad market conditions today
2. Call `get_economic_indicators()` → interest rate, CPI, GDP environment
3. Use `search_market_history(query)` → historical analogies if relevant
4. Synthesize: How does the macro environment support or threaten this stock?

### B. Regulatory/filing deep dive
1. Call `get_sec_filing_summary(ticker, form_type="10-K")` → key risk factors
2. Cross-reference with `get_fundamental_data` (from fundamental skill)
3. Identify: Are risks priced in? Are there red flags?

### C. Market cycle assessment
1. Call `get_economic_indicators()` → where are we in the cycle?
2. Call `search_market_history("bear market characteristics")` → historical parallels
3. Recommend positioning based on cycle phase

### D. Top-down conviction synthesis (Druckenmiller-style)
For "how should I be positioned overall?" / "what's my conviction level?"
questions, run the market-timing tools together and synthesize in one pass
rather than in isolation (this replaces the original multi-skill
file-pipeline design — no `reports/` directory needed here):
1. Call `get_market_breadth()` → participation health
2. Call `get_market_timing_signals()` → distribution/FTD state
3. Call `get_macro_regime()` → structural regime
4. Call `assess_market_risk()` → tactical top/bubble risk
5. Weigh them together: strong breadth + no distribution risk + favorable
   regime + low top-risk = high conviction (lean toward fuller exposure);
   conflicting signals = moderate conviction (reduce size, don't force a
   view); deteriorating breadth + rising distribution days + elevated top
   risk = low conviction (capital preservation). State which signals agree
   and which conflict — don't average away a genuine disagreement.
6. Frame the recommendation as an exposure *range*, not a single number, and
   name the specific signal that would change your mind (Druckenmiller's
   "when you don't see it, don't swing" — low conviction is itself a
   legitimate answer).

## Output Format

```
## Macro & Market Context

### Current Market Conditions
- S&P 500: {price} ({change})  |  VIX: {vix} ({low/moderate/high} fear)
- NASDAQ: {price} ({change})

### Economic Indicators
- Fed Funds Rate: {rate}% ({rising/stable/falling})
- CPI (YoY): {cpi}% ({above/below 2% target})
- GDP Growth: {gdp}% ({expanding/contracting})
- Unemployment: {unemployment}%

### Macro Assessment
- Rate Environment: {Restrictive/Neutral/Accommodative}
- Impact on {sector}: {positive/neutral/negative}
- Key macro risk: ...

### Historical Context (if applicable)
- Current situation resembles: {event}
- Key difference: ...
- Historical playbook: ...
```
