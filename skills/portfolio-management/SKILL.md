# Portfolio Management Skill

## Overview
This skill handles multi-stock analysis, portfolio construction, risk metrics,
and allocation recommendations. Use it when asked to compare multiple stocks,
evaluate an existing portfolio, calculate risk-adjusted returns, or suggest
position sizing.

## Available Tools

### `calculate_portfolio_metrics`
Calculates portfolio-level return, volatility, Sharpe ratio, max drawdown,
and per-position breakdown.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `holdings` | JSON array: `'[{"ticker":"AAPL","weight":0.4},{"ticker":"MSFT","weight":0.6}]'` | required |
| `period` | `1mo` `3mo` `6mo` `1y` `2y` `5y` | `1y` |

**Tip**: Weights must sum to 1.0. If omitted, equal weighting is assumed.

---

### `compare_stocks`
Side-by-side comparison of multiple stocks by price performance, valuation,
and key ratios. Ranks them by return over the specified period.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `tickers` | Comma-separated: `"NVDA,AMD,INTC"` | required |
| `period`  | `1mo` `3mo` `6mo` `1y` `2y` `5y` | `1y` |

---

## Standard Workflows

### A. Compare multiple stocks (no existing portfolio)
1. Call `compare_stocks(tickers, period)` → get performance ranking + valuation table
2. Identify the top performers and their risk profiles
3. Suggest an allocation weighted by risk-adjusted return

### B. Evaluate an existing portfolio
1. Call `calculate_portfolio_metrics(holdings, period)` → get total return, Sharpe, max drawdown
2. Review per-position contributions
3. Identify concentration risks (any single position >40%)
4. Check Sharpe ratio: >1.0 acceptable, >2.0 excellent
5. Recommend rebalancing if needed

### C. Build an optimal portfolio from candidates
1. Call `compare_stocks(candidates, period)` → rank by performance
2. Call `calculate_portfolio_metrics` with proposed equal weights → baseline metrics
3. Adjust weights toward top performers, recalculate until Sharpe improves
4. Recommend final allocation with rationale

## Risk Interpretation Guide

| Metric | Range | Assessment |
|--------|-------|------------|
| Sharpe Ratio | > 2.0 | Excellent |
| Sharpe Ratio | 1.0 – 2.0 | Good |
| Sharpe Ratio | 0.5 – 1.0 | Acceptable |
| Sharpe Ratio | < 0.5 | Poor |
| Max Drawdown | < -10% | Low risk |
| Max Drawdown | -10% to -25% | Moderate risk |
| Max Drawdown | > -25% | High risk |
| Annual Volatility | < 15% | Low |
| Annual Volatility | 15–30% | Moderate |
| Annual Volatility | > 30% | High |

## Output Format

```
## Portfolio Analysis

### Comparison Table
| Ticker | Return ({period}) | P/E | Market Cap | Analyst |
|--------|------------------|-----|------------|---------|
| ...    | ...              | ... | ...        | ...     |

**Performance Rank**: {ticker1} > {ticker2} > {ticker3}

### Portfolio Metrics ({period})
| Metric | Value |
|--------|-------|
| Total Return | XX.XX% |
| Annualized Volatility | XX.XX% |
| Sharpe Ratio | X.XX |
| Max Drawdown | -XX.XX% |

### Position Breakdown
| Ticker | Weight | Return | Volatility |
|--------|--------|--------|------------|
| ...    | XX%    | XX%    | XX%        |

### Risk Assessment
- Concentration risk: {Low/Medium/High}
- Diversification: {comment}

### Recommendation
- Suggested allocation: {ticker}: XX%, {ticker}: XX%, ...
- Rationale: ...
- Key risk: ...
```
