"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           Stock Analysis Deep Agent – MCP Streamable HTTP Server             ║
║                                                                              ║
║  This file exposes all stock analysis tools via MCP Streamable HTTP          ║
║  transport so Claude.ai (online version) can connect as a Custom Connector.  ║
║                                                                              ║
║  Usage:                                                                      ║
║    1. python mcp_sse_server.py          # starts on http://localhost:8001    ║
║    2. ngrok http 8001                   # expose via public HTTPS URL        ║
║    3. Add the ngrok URL to Claude.ai:                                        ║
║       Settings → Customize → Connectors → + Add custom connector             ║
║       URL: https://xxxx.ngrok-free.app/mcp                                  ║
║                                                                              ║
║  NOTE: This server is separate from mcp_server.py (stdio mode).              ║
║  Both can run simultaneously without conflict.                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env ──────────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

# ── Ensure local modules are importable ───────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# ── Import tool implementations from mcp_server.py (no duplication) ──────────
from mcp_server import (
    _get_stock_price,
    _calculate_technical_indicators,
    _get_fundamental_data,
    _compare_stocks,
    _get_market_overview,
    _get_economic_indicators,
    _get_sec_filing_summary,
)

# Also import portfolio skill directly
import json

# ── FastMCP setup ──────────────────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("❌ FastMCP not found. Please upgrade the mcp package:")
    print("   pip install --upgrade mcp")
    sys.exit(1)

PORT = int(os.environ.get("MCP_SSE_PORT", "8001"))

mcp = FastMCP(
    "stock-analysis",
    host="0.0.0.0",
    port=PORT,
    instructions=(
        "You are connected to a Stock Analysis Agent with real-time market data tools. "
        "You can fetch live stock prices, calculate technical indicators (RSI, MACD, Bollinger Bands), "
        "retrieve fundamental financial data, compare multiple stocks, analyse portfolios, "
        "get macroeconomic indicators (Fed rate, CPI, GDP), and retrieve SEC filings. "
        "Always cite specific numbers. This is for educational purposes, not financial advice."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Tool Definitions
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_stock_price(ticker: str, period: str = "1mo") -> dict:
    """
    Fetch current price, historical OHLCV data, and key statistics for a stock.

    Args:
        ticker: Stock ticker symbol e.g. AAPL, TSLA, 2330.TW (Taiwan), 005930.KS (Korea)
        period: Historical period — 1d | 5d | 1mo | 3mo | 6mo | 1y | 2y | 5y | ytd | max
    Returns:
        dict with current_price, change_pct, 52w_high/low, market_cap, and recent OHLCV data
    """
    return _get_stock_price(ticker, period)


@mcp.tool()
def calculate_technical_indicators(ticker: str, period: str = "6mo") -> dict:
    """
    Calculate technical analysis indicators for a stock.
    Includes: SMA (20/50/200), EMA, RSI-14, MACD, Bollinger Bands, ATR, volume trend,
    and auto-generated buy/sell signal summary.

    Args:
        ticker: Stock ticker symbol e.g. AAPL
        period: Historical period for calculation (default: 6mo)
    Returns:
        dict with all technical indicators and a signal_summary list
    """
    return _calculate_technical_indicators(ticker, period)


@mcp.tool()
def get_fundamental_data(ticker: str) -> dict:
    """
    Retrieve fundamental financial data for a stock.
    Includes: P/E ratio (trailing & forward), PEG, P/B, profit margins, ROE,
    revenue, free cash flow, EPS, dividend yield, debt-to-equity, and analyst rating.

    Args:
        ticker: Stock ticker symbol e.g. AAPL
    Returns:
        dict with valuation ratios, profitability metrics, and analyst recommendation
    """
    return _get_fundamental_data(ticker)


@mcp.tool()
def compare_stocks(tickers: str, period: str = "1y") -> dict:
    """
    Compare multiple stocks side-by-side on price performance, valuation, and analyst recommendations.

    Args:
        tickers: Comma-separated ticker symbols e.g. "AAPL,MSFT,GOOGL" or "NVDA,AMD,INTC"
        period: Performance comparison period (default: 1y)
    Returns:
        dict with side-by-side comparison table of all stocks
    """
    return _compare_stocks(tickers, period)


@mcp.tool()
def calculate_portfolio_metrics(holdings: str, period: str = "1y") -> dict:
    """
    Calculate portfolio metrics for a weighted set of stocks.
    Includes: total return, annualised volatility, Sharpe ratio, and max drawdown.

    Args:
        holdings: JSON array e.g. '[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]'
                  OR comma-separated tickers for equal-weight e.g. "AAPL,MSFT,GOOGL"
        period:   Historical period (default: 1y)
    Returns:
        dict with portfolio performance metrics and individual stock contributions
    """
    try:
        from skills import calculate_portfolio_metrics as _pm
        result = _pm.invoke({"holdings": holdings, "period": period})
        return json.loads(result) if isinstance(result, str) else result
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_market_overview() -> dict:
    """
    Get a real-time snapshot of major global market indices and commodities.
    Covers: S&P 500, NASDAQ, DOW Jones, VIX fear index, Gold, and WTI Oil.

    Returns:
        dict with current price, daily change, and percentage change for each index
    """
    return _get_market_overview()


@mcp.tool()
def get_economic_indicators(indicators: str = "all") -> dict:
    """
    Fetch live US macroeconomic indicators from FRED (Federal Reserve Economic Data).
    Use for questions about monetary policy, inflation, economic outlook, or macro context.

    Args:
        indicators: Comma-separated list or 'all'.
                    Options: fed_rate, cpi, gdp, unemployment, treasury_10y, treasury_2y
    Returns:
        dict with current values, units, descriptions, and yield curve spread signal
    """
    return _get_economic_indicators(indicators)


@mcp.tool()
def get_sec_filing_summary(ticker: str, form_type: str = "10-K") -> dict:
    """
    Retrieve the most recent SEC regulatory filing for a US-listed company via SEC EDGAR.
    Returns filing date, accession number, and direct document URL to the actual SEC filing.

    Args:
        ticker:    US stock ticker e.g. AAPL, TSLA, MSFT
        form_type: '10-K' (annual report, default) or '10-Q' (quarterly report)
    Returns:
        dict with company info, CIK, filing dates, and document URLs
    """
    return _get_sec_filing_summary(ticker, form_type)


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PORT = int(os.environ.get("MCP_SSE_PORT", "8001"))

    print("=" * 65)
    print("  📈 Stock Analysis MCP Server (Streamable HTTP)")
    print("=" * 65)
    print(f"  ✅ Local endpoint : http://localhost:{PORT}")
    print()
    print("  Next steps:")
    print(f"  1. Keep this running")
    print(f"  2. In a NEW terminal, run:")
    print(f"     ngrok http {PORT} (or cloudflared)")
    print(f"  3. Copy the public HTTPS URL (e.g. https://xxxx.trycloudflare.com)")
    print(f"  4. In Claude.ai → Settings → Customize → Connectors")
    print(f"     → + Add custom connector")
    print(f"     → URL: https://xxxx.trycloudflare.com/mcp")
    print("=" * 65)
    print()

    # Run FastMCP with streamable-http transport (required by Claude.ai web)
    mcp.run(transport="streamable-http")



