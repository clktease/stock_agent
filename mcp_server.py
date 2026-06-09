"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    Stock Analysis Deep Agent – MCP Server                    ║
║                                                                              ║
║  This file exposes stock analysis tools as a Model Context Protocol (MCP)    ║
║  server. Run it standalone so any MCP-compatible client can connect and       ║
║  use your stock analysis capabilities.                                        ║
║                                                                              ║
║  Usage:                                                                      ║
║    python mcp_server.py                          # stdio transport           ║
║    python mcp_server.py --transport sse          # SSE transport             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import json
import math
import warnings
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    TextContent,
    Tool,
)
import mcp.types as types

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# MCP Server Setup
# ─────────────────────────────────────────────────────────────────────────────

app = Server("stock-analysis-mcp")


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(v) -> Any:
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 4)
    except Exception:
        return None


def _fmt(n) -> str:
    try:
        n = float(n)
        if n >= 1e12: return f"${n/1e12:.2f}T"
        if n >= 1e9:  return f"${n/1e9:.2f}B"
        if n >= 1e6:  return f"${n/1e6:.2f}M"
        return f"${n:,.2f}"
    except Exception:
        return "N/A"


def _result(data: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False, default=str))]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tool Definitions (JSON Schema)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="get_stock_price",
        description="Fetch current price, historical OHLCV data, and key statistics for a stock ticker.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol e.g. AAPL"},
                "period": {
                    "type": "string",
                    "description": "Historical period: 1d|5d|1mo|3mo|6mo|1y|2y|5y|ytd|max",
                    "default": "1mo",
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="calculate_technical_indicators",
        description=(
            "Calculate technical analysis indicators: SMA/EMA (20,50,200), RSI-14, "
            "MACD, Bollinger Bands, ATR, and volume trend with buy/sell signals."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "period": {"type": "string", "description": "History period (default: 6mo)", "default": "6mo"},
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_fundamental_data",
        description=(
            "Retrieve fundamental financial data: valuation ratios (P/E, PEG, P/B), "
            "profitability, growth, dividends, balance sheet, and analyst ratings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="compare_stocks",
        description="Compare multiple stocks side-by-side on price performance, valuation, and analyst recommendations.",
        inputSchema={
            "type": "object",
            "properties": {
                "tickers": {"type": "string", "description": "Comma-separated tickers e.g. AAPL,MSFT,GOOGL"},
                "period":  {"type": "string", "description": "Performance period (default: 1y)", "default": "1y"},
            },
            "required": ["tickers"],
        },
    ),
    Tool(
        name="calculate_portfolio_metrics",
        description=(
            "Calculate portfolio metrics: total return, annualized volatility, Sharpe ratio, "
            "and max drawdown for a weighted portfolio of stocks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "holdings": {
                    "type": "string",
                    "description": (
                        'JSON array of holdings e.g. [{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}] '
                        'or comma-separated tickers for equal-weight'
                    ),
                },
                "period": {"type": "string", "description": "Historical period (default: 1y)", "default": "1y"},
            },
            "required": ["holdings"],
        },
    ),
    Tool(
        name="get_market_overview",
        description="Get a snapshot of major market indices (S&P 500, NASDAQ, DOW, VIX) and their daily performance.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Tool Implementations
# ─────────────────────────────────────────────────────────────────────────────

def _get_stock_price(ticker: str, period: str = "1mo") -> dict:
    stock = yf.Ticker(ticker.upper())
    info  = stock.info
    hist  = stock.history(period=period)

    if hist.empty:
        return {"error": f"No data for {ticker}"}

    cur  = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else cur
    chg  = round(cur - prev, 4)
    chg_pct = round(chg / prev * 100, 2) if prev else 0

    recent = hist.tail(10).copy()
    recent.index = recent.index.strftime("%Y-%m-%d")
    ohlcv = recent[["Open", "High", "Low", "Close", "Volume"]].round(2).to_dict(orient="index")

    return {
        "ticker": ticker.upper(),
        "name": info.get("longName", ticker),
        "current_price": round(cur, 2),
        "currency": info.get("currency", "USD"),
        "change": chg,
        "change_pct": f"{chg_pct}%",
        "52w_high": _safe_float(info.get("fiftyTwoWeekHigh")),
        "52w_low":  _safe_float(info.get("fiftyTwoWeekLow")),
        "market_cap": _fmt(info.get("marketCap")),
        "period": period,
        "data_points": len(hist),
        "recent_ohlcv": ohlcv,
    }


def _calculate_technical_indicators(ticker: str, period: str = "6mo") -> dict:
    hist  = yf.Ticker(ticker.upper()).history(period=period)
    if hist.empty or len(hist) < 30:
        return {"error": f"Insufficient data for {ticker}"}

    close = hist["Close"]
    high  = hist["High"]
    low   = hist["Low"]
    vol   = hist["Volume"]

    # Moving Averages
    sma20  = float(close.rolling(20).mean().iloc[-1])
    sma50  = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

    # RSI
    delta = close.diff()
    rsi = float((100 - 100 / (1 + delta.clip(lower=0).rolling(14).mean() /
                (-delta.clip(upper=0)).rolling(14).mean())).iloc[-1])

    # MACD
    macd   = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()

    # Bollinger Bands
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_up  = bb_mid + 2 * bb_std
    bb_lo  = bb_mid - 2 * bb_std
    cur    = float(close.iloc[-1])
    bb_pct = float((cur - bb_lo.iloc[-1]) / (bb_up.iloc[-1] - bb_lo.iloc[-1]) * 100) \
             if (bb_up.iloc[-1] - bb_lo.iloc[-1]) != 0 else 50

    # ATR
    tr  = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    signals = []
    if rsi > 70: signals.append("🔴 RSI overbought")
    elif rsi < 30: signals.append("🟢 RSI oversold – potential bounce")
    if float(macd.iloc[-1]) > 0: signals.append("🟢 MACD positive")
    else: signals.append("🔴 MACD negative")
    if cur > sma20: signals.append("🟢 Above SMA20")
    if sma50 and cur > sma50: signals.append("🟢 Above SMA50")
    if bb_pct > 80: signals.append("⚠️ Near upper Bollinger Band")
    elif bb_pct < 20: signals.append("⚠️ Near lower Bollinger Band")

    return {
        "ticker": ticker.upper(),
        "current_price": round(cur, 2),
        "sma_20": round(sma20, 2),
        "sma_50": round(sma50, 2) if sma50 else None,
        "sma_200": round(sma200, 2) if sma200 else None,
        "rsi_14": round(rsi, 2),
        "macd": round(float(macd.iloc[-1]), 4),
        "macd_signal": round(float(signal.iloc[-1]), 4),
        "macd_histogram": round(float((macd - signal).iloc[-1]), 4),
        "bollinger_upper": round(float(bb_up.iloc[-1]), 2),
        "bollinger_lower": round(float(bb_lo.iloc[-1]), 2),
        "bollinger_pct_b": round(bb_pct, 1),
        "atr_14": round(atr, 2),
        "signal_summary": signals,
    }


def _get_fundamental_data(ticker: str) -> dict:
    info = yf.Ticker(ticker.upper()).info

    def pct(v): return f"{(_safe_float(v) or 0) * 100:.2f}%"

    return {
        "ticker": ticker.upper(),
        "name": info.get("longName", ticker),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "market_cap": _fmt(info.get("marketCap")),
        "pe_trailing": _safe_float(info.get("trailingPE")),
        "pe_forward":  _safe_float(info.get("forwardPE")),
        "peg_ratio":   _safe_float(info.get("pegRatio")),
        "price_to_book": _safe_float(info.get("priceToBook")),
        "profit_margin": pct(info.get("profitMargins")),
        "roe": pct(info.get("returnOnEquity")),
        "revenue_ttm": _fmt(info.get("totalRevenue")),
        "free_cash_flow": _fmt(info.get("freeCashflow")),
        "eps_trailing": _safe_float(info.get("trailingEps")),
        "eps_forward":  _safe_float(info.get("forwardEps")),
        "dividend_yield": pct(info.get("dividendYield")),
        "debt_to_equity": _safe_float(info.get("debtToEquity")),
        "current_ratio":  _safe_float(info.get("currentRatio")),
        "analyst_recommendation": info.get("recommendationKey", "N/A").upper(),
        "target_price_mean": _safe_float(info.get("targetMeanPrice")),
    }


def _compare_stocks(tickers: str, period: str = "1y") -> dict:
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    results = []
    for sym in ticker_list:
        try:
            info = yf.Ticker(sym).info
            hist = yf.Ticker(sym).history(period=period)
            perf = round((float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1) * 100, 2) if len(hist) > 1 else None
            results.append({
                "ticker": sym,
                "name": info.get("longName", sym)[:35],
                "sector": info.get("sector", "N/A"),
                "price": round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else None,
                f"return_{period}": f"{perf}%" if perf is not None else "N/A",
                "market_cap": _fmt(info.get("marketCap")),
                "pe_trailing": _safe_float(info.get("trailingPE")),
                "analyst_rec": info.get("recommendationKey", "N/A").upper(),
            })
        except Exception as e:
            results.append({"ticker": sym, "error": str(e)})
    return {"period": period, "comparison": results}


def _get_market_overview() -> dict:
    indices = {
        "S&P 500": "^GSPC",
        "NASDAQ":  "^IXIC",
        "DOW":     "^DJI",
        "VIX":     "^VIX",
        "Gold":    "GC=F",
        "Oil WTI": "CL=F",
    }
    snapshot = {}
    for name, sym in indices.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if len(hist) >= 2:
                cur  = round(float(hist["Close"].iloc[-1]), 2)
                prev = round(float(hist["Close"].iloc[-2]), 2)
                chg  = round(cur - prev, 2)
                chg_pct = round(chg / prev * 100, 2)
                snapshot[name] = {"price": cur, "change": chg, "change_pct": f"{chg_pct}%"}
        except Exception:
            snapshot[name] = {"error": "unavailable"}
    return {"as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), "indices": snapshot}


# ─────────────────────────────────────────────────────────────────────────────
# MCP Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "get_stock_price":
            data = _get_stock_price(arguments["ticker"], arguments.get("period", "1mo"))
        elif name == "calculate_technical_indicators":
            data = _calculate_technical_indicators(arguments["ticker"], arguments.get("period", "6mo"))
        elif name == "get_fundamental_data":
            data = _get_fundamental_data(arguments["ticker"])
        elif name == "compare_stocks":
            data = _compare_stocks(arguments["tickers"], arguments.get("period", "1y"))
        elif name == "calculate_portfolio_metrics":
            from skills import calculate_portfolio_metrics
            result = calculate_portfolio_metrics.invoke({
                "holdings": arguments["holdings"],
                "period": arguments.get("period", "1y"),
            })
            data = json.loads(result) if isinstance(result, str) else result
        elif name == "get_market_overview":
            data = _get_market_overview()
        else:
            data = {"error": f"Unknown tool: {name}"}
    except Exception as e:
        data = {"error": str(e), "tool": name}

    return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False, default=str))]


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read, write):
        await app.run(
            read,
            write,
            InitializationOptions(
                server_name="stock-analysis-mcp",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio
    print("🚀 Stock Analysis MCP Server starting (stdio mode)…")
    asyncio.run(main())
