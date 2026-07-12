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

### `calculate_position_size`
Risk-based share sizing for a long trade: Fixed Fractional, ATR-based, and
Kelly Criterion (half-Kelly applied), with optional portfolio concentration
constraints (`max_position_pct`, `max_sector_pct`). Always rounds shares
down; reports which constraint (if any) bound the final size.

**When to use**: "how many shares should I buy?", "what's my position size
at 1% risk?", Kelly Criterion questions, checking a trade against portfolio
concentration limits.

---

### `calculate_option_strategy`
Prices an options strategy leg-by-leg with Black-Scholes, sums position
Greeks, and simulates P/L across a price range to find max profit/loss and
breakeven(s). Supports long call/put, covered call, protective put, bull/bear
call/put spreads, long straddle/strangle, and iron condor (single expiration
only — no calendar/diagonal spreads).

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `ticker` | Underlying ticker | required |
| `strategy` | `long_call` `long_put` `covered_call` `protective_put` `bull_call_spread` `bear_put_spread` `bull_put_spread` `bear_call_spread` `long_straddle` `long_strangle` `iron_condor` | required |
| `days_to_expiration` | Days to expiry | `30` |
| `volatility` | IV as decimal, e.g. `0.25`; omit to use 6mo historical volatility | none |

**When to use**: "analyze a covered call on X", "what's my max profit on a
bull call spread?", "should I trade a straddle before earnings?". Theoretical
pricing only — always note actual market/bid-ask prices will differ.

---

### `find_pair_trade_candidates`
Market-neutral statistical arbitrage screen for a user-supplied ticker list
(not a full-universe scan): pairwise correlation, hedge ratio (beta),
cointegration (Augmented Dickey-Fuller test), spread half-life, and current
z-score, ranked by statistical strength.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `tickers` | Comma-separated, max 12: `"AAPL,MSFT,GOOGL,META,NVDA"` | required |
| `min_correlation` | Minimum Pearson correlation to consider | `0.70` |

**When to use**: "find pair trading opportunities in tech", "are AAPL and
MSFT cointegrated?", market-neutral / mean-reversion strategy requests.

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

## Backtesting Rigor Checklist

When a user asks you to validate, stress-test, or judge whether a systematic
trading idea is robust (not just whether it made money on paper), apply this
checklist rather than taking a single backtest run at face value:

1. **State the hypothesis in one sentence.** If it can't be stated without
   hedging, it's not ready to test.
2. **Codify every rule with zero discretion** — entry, exit, position sizing,
   filters, universe. No "use judgment" steps.
3. **Minimum 5 years, multiple regimes, realistic costs** for the initial run.
4. **Stress test (spend ~80% of effort here, not on the first pass):**
   - Parameter sensitivity — look for stable *plateaus*, not a single sharp
     optimum (a strategy that only works at stop-loss = 2.13% is curve-fit).
   - Slippage 1.5-2x typical, worst-case fills, pessimistic commissions.
   - Year-by-year performance — should be positive in most years, not carried
     by 1-2 exceptional periods.
   - Sample size: 30 trades minimum, 100+ preferred, 200+ for high confidence.
5. **Out-of-sample / walk-forward validation.** Red flag if out-of-sample
   performance is <50% of in-sample, or parameters need frequent re-tuning.
6. **Red flags that should trigger a harder look**: >90% win rate, minimal
   drawdowns, "too good to be true" results — audit for look-ahead or
   survivorship bias before accepting them.

Verdict framework: **Deploy** (survives stress tests), **Refine** (sound
logic, needs parameter adjustment), or **Abandon** (fails stress tests or
depends on fragile assumptions). When asked to "beat an idea to death,"
default to pessimistic assumptions — a strategy that survives friction is
more trustworthy than one that looks great with none.
