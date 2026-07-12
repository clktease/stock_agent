# Technical Analysis Skill

## Overview
This skill enables in-depth technical analysis of equity price data using a suite of
chart indicators. Use it when asked to evaluate price trends, momentum, volatility,
or generate buy/sell signals for a stock.

## Available Tools

### `get_stock_price`
Fetches the current price snapshot and recent OHLCV history for a ticker.

**When to call first**: Always call this before running indicators so you have
current price context (52-week range, market cap, day change).

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `ticker`  | e.g. `"AAPL"`, `"2330.TW"` | required |
| `period`  | `1d` `5d` `1mo` `3mo` `6mo` `1y` `2y` `5y` | `1mo` |

---

### `calculate_technical_indicators`
Computes RSI, MACD, Bollinger Bands, SMA/EMA, ATR, and volume trend.
Returns a pre-built `signal_summary` list in plain English.

**When to call**: After `get_stock_price`, use this to compute indicators.
Use at least `6mo` of data for reliable RSI and MACD values.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `ticker`  | e.g. `"AAPL"` | required |
| `period`  | `3mo` `6mo` `1y` | `6mo` |

---

### `analyze_downtrend_durations`
Analyzes historical peak-to-trough downtrend durations for a list of tickers
to set realistic expectations for correction length (mean-reversion holding
periods, stop-loss timeouts). Reports median/mean/percentile duration overall
and by market-cap tier.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `tickers` | Comma-separated, max 15 | required |
| `lookback_years` | Years of history | `5` |

**When to call**: "how long do corrections typically last for this stock/sector?",
setting a time-based stop, comparing correction behavior by market-cap tier.

---

## Standard Workflow

1. Call `get_stock_price(ticker, period="1mo")` → get current price, 52w high/low, market cap
2. Call `calculate_technical_indicators(ticker, period="6mo")` → get RSI, MACD, Bollinger Bands, signal summary
3. Interpret each indicator group:
   - **Trend**: Price vs SMA20 / SMA50 / SMA200 → Uptrend / Downtrend / Sideways
   - **Momentum**: RSI 14 → >70 Overbought, <30 Oversold, 30–70 Neutral
   - **MACD**: MACD line vs signal line + histogram direction → Bullish / Bearish / Mixed
   - **Volatility**: Bollinger %b → >80% near upper band (overbought zone), <20% near lower band
   - **Volume**: 5d vs 20d average ratio → >1.5x means volume surge
4. Conclude with a structured technical outlook:
   - Overall bias: **Bullish / Bearish / Neutral**
   - Key support level (e.g. SMA20 or lower Bollinger Band)
   - Key resistance level (e.g. 52w high or upper Bollinger Band)
   - Confidence: High / Medium / Low

## Output Format

```
## Technical Analysis — {TICKER}

**Current Price**: $XXX.XX  |  52w Range: $XX–$XXX

### Trend
- SMA20: $XXX (price is above/below → short-term uptrend/downtrend)
- SMA50: $XXX (price is above/below → medium-term uptrend/downtrend)

### Momentum
- RSI(14): XX.X → Neutral / Overbought / Oversold

### MACD
- MACD: X.XXXX | Signal: X.XXXX | Histogram: X.XXXX → Bullish/Bearish/Mixed

### Volatility
- Bollinger %b: XX.X% → Near upper/lower/middle band

### Volume
- 5d avg: X.XM vs 20d avg: X.XM (ratio: X.XX)

### Signal Summary
{paste signal_summary list from tool output}

### Technical Outlook
- **Bias**: Bullish / Bearish / Neutral
- **Support**: $XXX
- **Resistance**: $XXX
- **Confidence**: High / Medium / Low
```
