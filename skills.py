"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          Stock Analysis Deep Agent - Skills (Custom Tools)                   ║
║  These skills are callable by the agent for specialized financial analysis   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Skills provided:
  - get_stock_price         : Fetch current & historical OHLCV price data
  - calculate_technical_indicators : Compute RSI, MACD, Bollinger Bands, etc.
  - get_fundamental_data    : Fetch P/E, EPS, dividends, balance sheet
  - screen_stocks           : Simple screener by market cap / sector
  - compare_stocks          : Side-by-side comparison of multiple tickers
  - calculate_portfolio_metrics : Compute portfolio return, volatility, Sharpe
"""

import json
import math
import warnings
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from langchain_core.tools import tool

warnings.filterwarnings("ignore")

import logging
# Suppress yfinance logging to avoid HTTP 404 noise in terminal/logs
logging.getLogger('yfinance').disabled = True
logging.getLogger('yfinance').propagate = False



# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value) -> Optional[float]:
    """Convert a value to float safely, returning None on failure."""
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_large_number(n) -> str:
    """Format large numbers with M / B / T suffix."""
    if n is None:
        return "N/A"
    try:
        n = float(n)
        if n >= 1e12:
            return f"${n / 1e12:.2f}T"
        if n >= 1e9:
            return f"${n / 1e9:.2f}B"
        if n >= 1e6:
            return f"${n / 1e6:.2f}M"
        return f"${n:,.2f}"
    except Exception:
        return "N/A"


# ─────────────────────────────────────────────────────────────────────────────
# Skill 1 – Stock Price Data
# ─────────────────────────────────────────────────────────────────────────────

@tool
def get_stock_price(ticker: str, period: str = "1mo") -> str:
    """
    Fetch current price and historical OHLCV data for a stock ticker.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA", "2330.TW")
        period: Time period – one of: "1d", "5d", "1mo", "3mo", "6mo",
                "1y", "2y", "5y", "ytd", "max". Default is "1mo".

    Returns:
        JSON string with current price, basic stats, and recent OHLCV data.
    """
    try:
        stock = yf.Ticker(ticker.upper())
        info = stock.info
        hist = stock.history(period=period)

        if hist.empty:
            return json.dumps({"error": f"No price data found for {ticker}. Check the ticker symbol."})

        # Current snapshot
        current_price = _safe_float(info.get("currentPrice") or hist["Close"].iloc[-1])
        prev_close    = _safe_float(info.get("previousClose") or hist["Close"].iloc[-2] if len(hist) > 1 else None)
        change        = round(current_price - prev_close, 4) if current_price and prev_close else None
        change_pct    = round((change / prev_close) * 100, 2) if change and prev_close else None

        # Historical OHLCV (last 10 trading days)
        recent = hist.tail(10).copy()
        recent.index = recent.index.strftime("%Y-%m-%d")
        ohlcv = recent[["Open", "High", "Low", "Close", "Volume"]].round(2).to_dict(orient="index")

        result = {
            "ticker": ticker.upper(),
            "name": info.get("longName", ticker),
            "current_price": current_price,
            "currency": info.get("currency", "USD"),
            "previous_close": prev_close,
            "change": change,
            "change_pct": f"{change_pct}%" if change_pct else "N/A",
            "day_high": _safe_float(info.get("dayHigh")),
            "day_low":  _safe_float(info.get("dayLow")),
            "52w_high": _safe_float(info.get("fiftyTwoWeekHigh")),
            "52w_low":  _safe_float(info.get("fiftyTwoWeekLow")),
            "avg_volume": info.get("averageVolume"),
            "market_cap": _format_large_number(info.get("marketCap")),
            "period_requested": period,
            "data_points": len(hist),
            "recent_ohlcv": ohlcv,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "ticker": ticker})


# ─────────────────────────────────────────────────────────────────────────────
# Skill 2 – Technical Indicators
# ─────────────────────────────────────────────────────────────────────────────

@tool
def calculate_technical_indicators(ticker: str, period: str = "6mo") -> str:
    """
    Calculate key technical analysis indicators for a stock.

    Indicators computed:
        - SMA (20, 50, 200-day Simple Moving Averages)
        - EMA (12, 26-day Exponential Moving Averages)
        - RSI (14-day Relative Strength Index)
        - MACD (12/26/9 MACD line, signal, histogram)
        - Bollinger Bands (20-day, 2σ)
        - ATR (14-day Average True Range)
        - Volume trend (5-day vs 20-day average)

    Args:
        ticker: Stock ticker symbol
        period: Historical period for calculation (default: "6mo")

    Returns:
        JSON with all computed indicators and a plain-English signal summary.
    """
    try:
        hist = yf.Ticker(ticker.upper()).history(period=period)
        if hist.empty or len(hist) < 30:
            return json.dumps({"error": f"Insufficient data for {ticker}. Need at least 30 trading days."})

        close  = hist["Close"]
        high   = hist["High"]
        low    = hist["Low"]
        volume = hist["Volume"]

        # ── Moving Averages ──────────────────────────────────────────────────
        sma20  = close.rolling(20).mean().iloc[-1]
        sma50  = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
        sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
        ema12  = close.ewm(span=12, adjust=False).mean().iloc[-1]
        ema26  = close.ewm(span=26, adjust=False).mean().iloc[-1]

        # ── RSI (14-day) ──────────────────────────────────────────────────────
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = (100 - (100 / (1 + rs))).iloc[-1]

        # ── MACD ──────────────────────────────────────────────────────────────
        macd_line   = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram   = macd_line - signal_line

        # ── Bollinger Bands ────────────────────────────────────────────────────
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        current_close = float(close.iloc[-1])

        bb_pct = float((current_close - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1]) * 100) \
                 if (bb_upper.iloc[-1] - bb_lower.iloc[-1]) != 0 else 50

        # ── ATR (14-day) ──────────────────────────────────────────────────────
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])

        # ── Volume Trend ──────────────────────────────────────────────────────
        vol5  = float(volume.tail(5).mean())
        vol20 = float(volume.tail(20).mean())
        vol_ratio = round(vol5 / vol20, 2) if vol20 else 1.0

        # ── Signal Summary ────────────────────────────────────────────────────
        signals = []
        rsi_val = float(rsi)
        if rsi_val > 70:
            signals.append("🔴 RSI overbought (>70) – possible reversal/pullback")
        elif rsi_val < 30:
            signals.append("🟢 RSI oversold (<30) – possible bounce/recovery")
        else:
            signals.append(f"🟡 RSI neutral ({rsi_val:.1f})")

        macd_val = float(macd_line.iloc[-1])
        hist_val = float(histogram.iloc[-1])
        if macd_val > 0 and hist_val > 0:
            signals.append("🟢 MACD bullish (above signal & zero line)")
        elif macd_val < 0 and hist_val < 0:
            signals.append("🔴 MACD bearish (below signal & zero line)")
        else:
            signals.append("🟡 MACD mixed signal")

        if sma20 and current_close > sma20:
            signals.append("🟢 Price above SMA20 (short-term uptrend)")
        else:
            signals.append("🔴 Price below SMA20 (short-term downtrend)")

        if sma50 and current_close > sma50:
            signals.append("🟢 Price above SMA50 (medium-term uptrend)")
        elif sma50:
            signals.append("🔴 Price below SMA50 (medium-term downtrend)")

        if bb_pct > 80:
            signals.append("⚠️  Price near upper Bollinger Band – overbought zone")
        elif bb_pct < 20:
            signals.append("⚠️  Price near lower Bollinger Band – oversold zone")

        if vol_ratio > 1.5:
            signals.append(f"📊 Volume surge: 5-day avg is {vol_ratio}x the 20-day average")

        result = {
            "ticker": ticker.upper(),
            "current_price": round(current_close, 2),
            "moving_averages": {
                "SMA_20":  round(float(sma20), 2) if sma20 else None,
                "SMA_50":  round(float(sma50), 2) if sma50 else None,
                "SMA_200": round(float(sma200), 2) if sma200 else None,
                "EMA_12":  round(float(ema12), 2),
                "EMA_26":  round(float(ema26), 2),
            },
            "rsi_14": round(rsi_val, 2),
            "macd": {
                "macd_line":    round(macd_val, 4),
                "signal_line":  round(float(signal_line.iloc[-1]), 4),
                "histogram":    round(hist_val, 4),
            },
            "bollinger_bands": {
                "upper": round(float(bb_upper.iloc[-1]), 2),
                "middle": round(float(bb_mid.iloc[-1]), 2),
                "lower": round(float(bb_lower.iloc[-1]), 2),
                "pct_b": round(bb_pct, 1),
            },
            "atr_14": round(atr, 2),
            "volume": {
                "5d_avg":  int(vol5),
                "20d_avg": int(vol20),
                "ratio":   vol_ratio,
            },
            "signal_summary": signals,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "ticker": ticker})


# ─────────────────────────────────────────────────────────────────────────────
# Skill 3 – Fundamental Data
# ─────────────────────────────────────────────────────────────────────────────

@tool
def get_fundamental_data(ticker: str) -> str:
    """
    Retrieve fundamental financial data for a stock.

    Data includes: valuation ratios, profitability, growth, dividends,
    balance sheet highlights, analyst ratings, and earnings estimates.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "MSFT", "2330.TW")

    Returns:
        JSON string with fundamental financial metrics.
    """
    try:
        stock = yf.Ticker(ticker.upper())
        info  = stock.info

        # ── Valuation ──────────────────────────────────────────────────────────
        valuation = {
            "market_cap":        _format_large_number(info.get("marketCap")),
            "enterprise_value":  _format_large_number(info.get("enterpriseValue")),
            "pe_trailing":       _safe_float(info.get("trailingPE")),
            "pe_forward":        _safe_float(info.get("forwardPE")),
            "peg_ratio":         _safe_float(info.get("pegRatio")),
            "price_to_book":     _safe_float(info.get("priceToBook")),
            "price_to_sales":    _safe_float(info.get("priceToSalesTrailing12Months")),
            "ev_to_ebitda":      _safe_float(info.get("enterpriseToEbitda")),
            "ev_to_revenue":     _safe_float(info.get("enterpriseToRevenue")),
        }

        # ── Profitability ──────────────────────────────────────────────────────
        def pct(v):
            x = _safe_float(v)
            return f"{x * 100:.2f}%" if x is not None else "N/A"

        profitability = {
            "gross_margin":       pct(info.get("grossMargins")),
            "operating_margin":   pct(info.get("operatingMargins")),
            "profit_margin":      pct(info.get("profitMargins")),
            "roe":                pct(info.get("returnOnEquity")),
            "roa":                pct(info.get("returnOnAssets")),
            "revenue_ttm":        _format_large_number(info.get("totalRevenue")),
            "ebitda":             _format_large_number(info.get("ebitda")),
            "free_cash_flow":     _format_large_number(info.get("freeCashflow")),
        }

        # ── Growth ────────────────────────────────────────────────────────────
        growth = {
            "revenue_growth_yoy": pct(info.get("revenueGrowth")),
            "earnings_growth_yoy": pct(info.get("earningsGrowth")),
            "earnings_quarterly_growth": pct(info.get("earningsQuarterlyGrowth")),
        }

        # ── Per Share ─────────────────────────────────────────────────────────
        per_share = {
            "eps_trailing": _safe_float(info.get("trailingEps")),
            "eps_forward":  _safe_float(info.get("forwardEps")),
            "book_value":   _safe_float(info.get("bookValue")),
        }

        # ── Dividends ────────────────────────────────────────────────────────
        dividends = {
            "dividend_rate":  _safe_float(info.get("dividendRate")),
            "dividend_yield": pct(info.get("dividendYield")),
            "payout_ratio":   pct(info.get("payoutRatio")),
            "ex_dividend_date": str(info.get("exDividendDate", "N/A")),
        }

        # ── Balance Sheet ────────────────────────────────────────────────────
        balance = {
            "total_cash":         _format_large_number(info.get("totalCash")),
            "total_debt":         _format_large_number(info.get("totalDebt")),
            "debt_to_equity":     _safe_float(info.get("debtToEquity")),
            "current_ratio":      _safe_float(info.get("currentRatio")),
            "quick_ratio":        _safe_float(info.get("quickRatio")),
        }

        # ── Analyst Ratings ───────────────────────────────────────────────────
        analyst = {
            "recommendation":    info.get("recommendationKey", "N/A").upper(),
            "target_price_mean": _safe_float(info.get("targetMeanPrice")),
            "target_price_high": _safe_float(info.get("targetHighPrice")),
            "target_price_low":  _safe_float(info.get("targetLowPrice")),
            "analyst_count":     info.get("numberOfAnalystOpinions"),
        }

        result = {
            "ticker":       ticker.upper(),
            "name":         info.get("longName", ticker),
            "sector":       info.get("sector", "N/A"),
            "industry":     info.get("industry", "N/A"),
            "country":      info.get("country", "N/A"),
            "employees":    info.get("fullTimeEmployees"),
            "description":  (info.get("longBusinessSummary") or "")[:400] + "…",
            "valuation":    valuation,
            "profitability": profitability,
            "growth":       growth,
            "per_share":    per_share,
            "dividends":    dividends,
            "balance_sheet": balance,
            "analyst_ratings": analyst,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "ticker": ticker})


# ─────────────────────────────────────────────────────────────────────────────
# Skill 4 – Stock Screener
# ─────────────────────────────────────────────────────────────────────────────

@tool
def screen_stocks(
    tickers: str,
    min_market_cap_b: float = 0,
    max_pe: float = 999,
    min_dividend_yield_pct: float = 0,
    sector: str = "",
) -> str:
    """
    Screen a list of stocks based on fundamental criteria.

    Args:
        tickers: Comma-separated list of ticker symbols, e.g. "AAPL,MSFT,GOOGL"
        min_market_cap_b: Minimum market cap in billions (default: 0 = no filter)
        max_pe: Maximum trailing P/E ratio (default: 999 = no filter)
        min_dividend_yield_pct: Minimum dividend yield in % (default: 0 = no filter)
        sector: Filter by sector name (e.g., "Technology"); empty = no filter

    Returns:
        JSON with screened stocks that pass all filters, sorted by market cap.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    results = []

    for sym in ticker_list:
        try:
            info = yf.Ticker(sym).info
            mc   = _safe_float(info.get("marketCap")) or 0
            pe   = _safe_float(info.get("trailingPE")) or 999
            dy   = (_safe_float(info.get("dividendYield")) or 0) * 100
            sec  = info.get("sector", "")

            if mc < min_market_cap_b * 1e9:
                continue
            if pe > max_pe:
                continue
            if dy < min_dividend_yield_pct:
                continue
            if sector and sector.lower() not in sec.lower():
                continue

            results.append({
                "ticker":          sym,
                "name":            info.get("longName", sym),
                "sector":          sec,
                "market_cap":      _format_large_number(mc),
                "pe_trailing":     round(pe, 2) if pe < 999 else None,
                "dividend_yield":  f"{dy:.2f}%",
                "52w_return":      f"{_safe_float(info.get('52WeekChange', 0)) * 100:.1f}%"
                                   if info.get("52WeekChange") else "N/A",
                "recommendation":  info.get("recommendationKey", "N/A").upper(),
            })
        except Exception:
            continue

    results.sort(key=lambda x: float(x["market_cap"].replace("$", "").replace("T", "e12")
                                     .replace("B", "e9").replace("M", "e6")
                                     .replace(",", "") or 0), reverse=True)

    return json.dumps({
        "screener_filters": {
            "min_market_cap_b": min_market_cap_b,
            "max_pe": max_pe,
            "min_dividend_yield_pct": min_dividend_yield_pct,
            "sector": sector or "Any",
        },
        "total_screened": len(ticker_list),
        "passed": len(results),
        "stocks": results,
    }, ensure_ascii=False, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# Skill 5 – Compare Stocks
# ─────────────────────────────────────────────────────────────────────────────

@tool
def compare_stocks(tickers: str, period: str = "1y") -> str:
    """
    Compare multiple stocks side-by-side including price performance,
    valuation, and key ratios.

    Args:
        tickers: Comma-separated ticker list, e.g. "AAPL,MSFT,GOOGL"
        period:  Historical period for performance calc (default: "1y")

    Returns:
        JSON with a comparison table and performance ranking.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    comparison  = []

    for sym in ticker_list:
        try:
            stock = yf.Ticker(sym)
            info  = stock.info
            hist  = stock.history(period=period)

            perf = None
            if not hist.empty and len(hist) > 1:
                perf = round((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2)

            comparison.append({
                "ticker":         sym,
                "name":           info.get("longName", sym)[:40],
                "sector":         info.get("sector", "N/A"),
                "price":          round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else None,
                f"return_{period}": f"{perf}%" if perf is not None else "N/A",
                "market_cap":     _format_large_number(info.get("marketCap")),
                "pe_trailing":    _safe_float(info.get("trailingPE")),
                "pe_forward":     _safe_float(info.get("forwardPE")),
                "pb_ratio":       _safe_float(info.get("priceToBook")),
                "rsi_14":         None,  # filled below if desired
                "dividend_yield": f"{(_safe_float(info.get('dividendYield')) or 0) * 100:.2f}%",
                "analyst_rec":    info.get("recommendationKey", "N/A").upper(),
            })
        except Exception as e:
            comparison.append({"ticker": sym, "error": str(e)})

    # Rank by performance
    valid = [s for s in comparison if f"return_{period}" in s and s[f"return_{period}"] != "N/A"]
    valid.sort(key=lambda x: float(x[f"return_{period}"].replace("%", "")), reverse=True)

    return json.dumps({
        "period":          period,
        "compared_tickers": ticker_list,
        "comparison":      comparison,
        "performance_rank": [s["ticker"] for s in valid],
    }, ensure_ascii=False, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# Skill 6 – Portfolio Metrics
# ─────────────────────────────────────────────────────────────────────────────

@tool
def calculate_portfolio_metrics(holdings: str, period: str = "1y") -> str:
    """
    Calculate portfolio-level metrics: total return, volatility, Sharpe ratio,
    max drawdown, and individual position performance.

    Args:
        holdings: JSON string with portfolio holdings.
                  Format: '[{"ticker":"AAPL","weight":0.4},{"ticker":"MSFT","weight":0.6}]'
                  Weights should sum to 1.0. Equal-weight assumed if omitted.
        period:   Historical period (default: "1y")

    Returns:
        JSON with portfolio metrics and individual position breakdown.
    """
    try:
        positions = json.loads(holdings)
    except json.JSONDecodeError:
        # Try parsing as comma-separated tickers
        tickers = [t.strip().upper() for t in holdings.split(",") if t.strip()]
        w = 1.0 / len(tickers)
        positions = [{"ticker": t, "weight": w} for t in tickers]

    tickers  = [p["ticker"].upper() for p in positions]
    weights  = np.array([p.get("weight", 1.0 / len(positions)) for p in positions])
    weights  = weights / weights.sum()  # normalize

    try:
        raw  = yf.download(tickers, period=period, auto_adjust=True, progress=False)
        closes = raw["Close"] if len(tickers) > 1 else raw["Close"].to_frame(tickers[0])

        if closes.empty:
            return json.dumps({"error": "No data downloaded for the given tickers."})

        closes.dropna(inplace=True)
        returns    = closes.pct_change().dropna()

        port_ret   = (returns * weights).sum(axis=1)
        cum_return = (1 + port_ret).cumprod()

        total_return  = float(cum_return.iloc[-1] - 1) * 100
        annual_vol    = float(port_ret.std() * math.sqrt(252)) * 100
        risk_free     = 0.05  # 5% annual
        sharpe        = (total_return / 100 / (len(port_ret) / 252) - risk_free) / (annual_vol / 100) \
                        if annual_vol else 0

        # Max drawdown
        rolling_max = cum_return.cummax()
        drawdown    = (cum_return - rolling_max) / rolling_max
        max_dd      = float(drawdown.min()) * 100

        # Individual position metrics
        positions_out = []
        for ticker, w in zip(tickers, weights):
            if ticker not in closes.columns:
                continue
            pos_ret = float(closes[ticker].iloc[-1] / closes[ticker].iloc[0] - 1) * 100
            pos_vol = float(returns[ticker].std() * math.sqrt(252)) * 100
            positions_out.append({
                "ticker":     ticker,
                "weight":     f"{w * 100:.1f}%",
                "return":     f"{pos_ret:.2f}%",
                "volatility": f"{pos_vol:.2f}%",
            })

        return json.dumps({
            "period":        period,
            "portfolio_metrics": {
                "total_return":  f"{total_return:.2f}%",
                "annualized_vol": f"{annual_vol:.2f}%",
                "sharpe_ratio":  round(sharpe, 2),
                "max_drawdown":  f"{max_dd:.2f}%",
            },
            "positions": positions_out,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def read_holdings_csv(file_path: str) -> str:
    """
    Read a stock holdings CSV file from disk and return its parsed contents.
    Use this tool to extract the list of stock tickers and their corresponding
    weights, allocations, or shares from a user-uploaded CSV file.

    Supports English and Traditional Chinese column names:
      - Ticker       : ticker / symbol / stock / code / 代號 / 股票代號
      - Weight / pct : weight / allocation / pct / 持倉佔比 / 佔比 / 比例
      - Market value : market value / 市值  (derives weights if no explicit weight col)
      - Shares       : shares / qty / quantity / 數量 / 股數

    Args:
        file_path: Absolute or relative path to the CSV file on disk.

    Returns:
        JSON string containing the parsed list of positions with keys 'ticker',
        'weight', 'shares' (if present), or an error message.
    """
    try:
        import os
        import pandas as pd

        if not os.path.exists(file_path):
            return json.dumps({"error": f"File not found: {file_path}"})

        df = pd.read_csv(file_path)
        if df.empty:
            return json.dumps({"error": "The uploaded CSV file is empty."})

        # Build mapping: stripped-original-name -> original column label
        col_map = {str(c).strip(): c for c in df.columns}

        # ── Column keyword sets ────────────────────────────────────────────────
        TICKER_EXACT = {
            "ticker", "symbol", "stock", "code", "shares symbol",
            "instrument", "代號", "股票代碼", "股票代號", "標的",
        }
        WEIGHT_EXACT = {
            "weight", "allocation", "percentage", "pct", "ratio", "proportion",
            "持倉佔比", "佔比", "比例", "配置", "权重",
        }
        MV_EXACT = {
            "市值", "market value", "market_value", "mv", "市場價值",
        }
        SHARES_EXACT = {
            "shares", "qty", "quantity", "amount", "units",
            "數量", "股數", "持股數",
        }

        def _find_col(exact_set, partial_kws):
            # 1) exact match (case-insensitive)
            for name, orig in col_map.items():
                if name in exact_set or name.lower() in exact_set:
                    return orig
            # 2) partial match
            for name, orig in col_map.items():
                if any(kw in name.lower() for kw in partial_kws):
                    return orig
            return None

        ticker_col = _find_col(TICKER_EXACT, ("ticker", "symbol", "stock", "代號", "股票"))
        if not ticker_col:
            ticker_col = df.columns[0]   # absolute fallback

        weight_col = _find_col(WEIGHT_EXACT, ("weight", "allocation", "pct", "percent", "佔比", "比例"))
        mv_col     = _find_col(MV_EXACT,     ("市值", "market", "mv"))
        shares_col = _find_col(SHARES_EXACT, ("share", "qty", "quant", "unit", "數量", "股數"))

        # ── Helper: parse pct string → decimal (0-1) ───────────────────────────
        def to_decimal_weight(val) -> Optional[float]:
            if val is None:
                return None
            has_pct = "%" in str(val)
            s = str(val).replace("%", "").replace(",", "").strip()
            try:
                f = float(s)
                if has_pct or f > 1.0:
                    return round(f / 100.0, 6)
                return round(f, 6)
            except (ValueError, TypeError):
                return None

        # ── Extract raw positions ──────────────────────────────────────────────
        positions = []
        for _, row in df.iterrows():
            ticker_val = str(row[ticker_col]).strip().upper()
            if not ticker_val or ticker_val in ("TICKER", "SYMBOL", "STOCK", "NAN", "", "代號"):
                continue

            pos: dict = {"ticker": ticker_val}

            if shares_col is not None:
                f_val = _safe_float(str(row[shares_col]).replace(",", ""))
                if f_val is not None:
                    pos["shares"] = f_val

            if mv_col is not None:
                f_val = _safe_float(str(row[mv_col]).replace(",", ""))
                if f_val is not None:
                    pos["_mv"] = f_val          # internal; removed after weight derivation

            if weight_col is not None:
                w = to_decimal_weight(row[weight_col])
                if w is not None:
                    pos["weight"] = w

            positions.append(pos)

        # ── Derive weights if not explicitly available ─────────────────────────
        all_have_weight = all("weight" in p for p in positions)
        weight_source = "explicit allocation column"

        if not all_have_weight:
            mv_positions = [p for p in positions if "_mv" in p]
            if mv_positions:
                total_mv = sum(p["_mv"] for p in mv_positions)
                if total_mv > 0:
                    for p in mv_positions:
                        p["weight"] = round(p["_mv"] / total_mv, 6)
                weight_source = "市值 (market value) — derived"
            else:
                eq_w = round(1.0 / len(positions), 6)
                for p in positions:
                    p["weight"] = eq_w
                weight_source = "equal weight (fallback — no weight/市值 column found)"

        # Remove internal key
        for p in positions:
            p.pop("_mv", None)

        # ── Normalise weights to sum = 1.0 ─────────────────────────────────────
        total_w = sum(p.get("weight", 0) for p in positions)
        if total_w > 0 and abs(total_w - 1.0) > 0.01:
            for p in positions:
                if "weight" in p:
                    p["weight"] = round(p["weight"] / total_w, 6)

        return json.dumps({
            "file_path": file_path,
            "columns_detected": {
                "ticker":       str(ticker_col),
                "weight":       str(weight_col) if weight_col else None,
                "market_value": str(mv_col)     if mv_col     else None,
                "shares":       str(shares_col) if shares_col else None,
            },
            "weight_source": weight_source,
            "holdings": positions,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"Failed to parse CSV: {str(e)}"})


# ─────────────────────────────────────────────────────────────────────────────
# Export all skills
# ─────────────────────────────────────────────────────────────────────────────

ALL_SKILLS = [
    get_stock_price,
    calculate_technical_indicators,
    get_fundamental_data,
    screen_stocks,
    compare_stocks,
    calculate_portfolio_metrics,
    read_holdings_csv,
]
