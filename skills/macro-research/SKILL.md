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
