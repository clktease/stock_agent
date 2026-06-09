# Fundamental Analysis Skill

## Overview
This skill retrieves and interprets a company's financial fundamentals — valuation
ratios, profitability metrics, growth rates, balance sheet health, and analyst
consensus. Use it when asked to evaluate whether a stock is cheap, fairly priced,
or overvalued, or to assess business quality.

## Available Tools

### `get_fundamental_data`
Fetches comprehensive financial data from Yahoo Finance for a given ticker.

**Returns**:
| Group | Key Metrics |
|-------|-------------|
| Valuation | P/E (trailing & forward), PEG, P/B, P/S, EV/EBITDA |
| Profitability | Gross/Operating/Net margins, ROE, ROA, Free Cash Flow |
| Growth | Revenue YoY, Earnings YoY, Quarterly earnings growth |
| Per Share | EPS (trailing & forward), Book Value |
| Dividends | Dividend rate, yield, payout ratio, ex-date |
| Balance Sheet | Cash, Total Debt, D/E ratio, Current & Quick ratios |
| Analyst Ratings | Recommendation, target price (mean/high/low), analyst count |

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `ticker`  | e.g. `"AAPL"`, `"TSLA"` | required |

---

## Standard Workflow

1. Call `get_fundamental_data(ticker)` → get all financial metrics
2. Assess **Valuation** — compare P/E to sector average and growth rate:
   - P/E < 15: potentially cheap
   - P/E 15–25: fairly valued for stable companies
   - P/E > 30: expensive unless growth justifies it
   - PEG < 1: undervalued relative to growth
3. Assess **Profitability** — are margins healthy and expanding?
   - Net margin >20% = excellent, >10% = good, <5% = thin
   - ROE >15% = strong capital efficiency
4. Assess **Growth** — revenue and earnings trajectory
5. Review **Balance Sheet** — debt sustainability
   - D/E < 1: conservative, D/E > 2: high leverage
   - Current ratio > 1.5: healthy liquidity
6. Check **Analyst Consensus** — compare current price to target range
7. Conclude with a fundamental rating:
   - **Undervalued / Fair Value / Overvalued**
   - Key bull and bear case

## Output Format

```
## Fundamental Analysis — {TICKER} ({Company Name})

**Sector**: {sector}  |  **Industry**: {industry}

### Valuation
| Metric | Value | Assessment |
|--------|-------|------------|
| P/E (TTM) | XX.X | Cheap / Fair / Expensive vs sector |
| Forward P/E | XX.X | ... |
| PEG Ratio | X.X | <1 = undervalued vs growth |
| Price/Book | X.X | ... |
| EV/EBITDA | XX.X | ... |

### Profitability
- Gross Margin: XX% | Operating Margin: XX% | Net Margin: XX%
- ROE: XX% | ROA: XX%
- Free Cash Flow: $X.XB

### Growth
- Revenue Growth (YoY): XX% | Earnings Growth (YoY): XX%

### Balance Sheet
- Cash: $X.XB | Total Debt: $X.XB | D/E: X.X
- Current Ratio: X.X | Quick Ratio: X.X

### Dividends
- Yield: X.XX% | Payout Ratio: XX%

### Analyst Consensus
- Rating: {BUY/HOLD/SELL}  ({N} analysts)
- Target: ${mean} (range: ${low}–${high}) vs current ${price}
- Upside/Downside to mean target: +/-XX%

### Fundamental Rating
**{Undervalued / Fair Value / Overvalued}**
- Bull case: ...
- Bear case: ...
```
