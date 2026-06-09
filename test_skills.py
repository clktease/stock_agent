"""
Test suite for the Stock Analysis Deep Agent skills.

Run with: python test_skills.py
"""

import json
import logging
import sys
import time
from rich.console import Console

# Suppress yfinance logging to avoid HTTP 404 noise in the test output
logging.getLogger('yfinance').disabled = True
logging.getLogger('yfinance').propagate = False

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Import skills
# ─────────────────────────────────────────────────────────────────────────────

try:
    from skills import (
        get_stock_price,
        calculate_technical_indicators,
        get_fundamental_data,
        screen_stocks,
        compare_stocks,
        calculate_portfolio_metrics,
    )
    console.print("[green]✓ Skills imported successfully[/green]")
except ImportError as e:
    console.print(f"[red]✗ Failed to import skills: {e}[/red]")
    console.print("Make sure you have installed dependencies: pip install -r requirements.txt")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Test Runner
# ─────────────────────────────────────────────────────────────────────────────

TESTS_PASSED = 0
TESTS_FAILED = 0


def run_test(name: str, func, args: dict, check_keys: list = None, expect_error: bool = False):
    global TESTS_PASSED, TESTS_FAILED
    console.print(f"\n[bold cyan]TEST:[/bold cyan] {name}")
    try:
        t0     = time.time()
        result = func.invoke(args)
        elapsed = round(time.time() - t0, 2)

        data = json.loads(result) if isinstance(result, str) else result

        if "error" in data:
            if expect_error:
                console.print(f"  [green]✓ Passed (gracefully handled expected error: {data['error']})[/green]")
                console.print(f"  [dim]({elapsed}s)[/dim]")
                TESTS_PASSED += 1
            else:
                console.print(f"  [yellow]⚠ Returned error: {data['error']}[/yellow]")
                console.print(f"  [dim]({elapsed}s)[/dim]")
                TESTS_FAILED += 1
            return data

        if expect_error:
            console.print(f"  [red]✗ Expected error but test succeeded[/red]")
            TESTS_FAILED += 1
            return data


        # Check required keys
        if check_keys:
            missing = [k for k in check_keys if k not in data]
            if missing:
                console.print(f"  [red]✗ Missing keys: {missing}[/red]")
                TESTS_FAILED += 1
                return data

        console.print(f"  [green]✓ Passed[/green] [dim]({elapsed}s)[/dim]")
        TESTS_PASSED += 1
        return data

    except Exception as e:
        console.print(f"  [red]✗ Exception: {e}[/red]")
        TESTS_FAILED += 1
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_all():
    console.print(Panel("[bold]🧪 Stock Analysis Skills – Test Suite[/bold]", style="blue"))

    # 1. Stock Price
    data = run_test(
        "get_stock_price – AAPL (1mo)",
        get_stock_price,
        {"ticker": "AAPL", "period": "1mo"},
        check_keys=["ticker", "current_price", "market_cap", "recent_ohlcv"],
    )
    if data:
        console.print(f"     AAPL: ${data.get('current_price')} | {data.get('change_pct')} | {data.get('market_cap')}")

    # 2. Invalid ticker
    data = run_test(
        "get_stock_price – invalid ticker (should return error gracefully)",
        get_stock_price,
        {"ticker": "XYZZZZ999"},
        check_keys=[],
        expect_error=True,
    )

    # 3. Technical Indicators
    data = run_test(
        "calculate_technical_indicators – MSFT (6mo)",
        calculate_technical_indicators,
        {"ticker": "MSFT", "period": "6mo"},
        check_keys=["ticker", "rsi_14", "macd", "bollinger_bands", "signal_summary"],
    )
    if data:
        console.print(f"     RSI: {data.get('rsi_14')} | MACD: {data.get('macd', {}).get('macd_line')}")
        for sig in (data.get("signal_summary") or [])[:3]:
            console.print(f"     {sig}")

    # 4. Fundamental Data
    data = run_test(
        "get_fundamental_data – GOOGL",
        get_fundamental_data,
        {"ticker": "GOOGL"},
        check_keys=["ticker", "valuation", "profitability", "analyst_ratings"],
    )
    if data:
        v = data.get("valuation", {})
        console.print(f"     P/E: {v.get('pe_trailing')} | Fwd P/E: {v.get('pe_forward')} | Sector: {data.get('sector')}")

    # 5. Stock Screener
    data = run_test(
        "screen_stocks – Tech mega-caps with P/E < 40",
        screen_stocks,
        {
            "tickers": "AAPL,MSFT,GOOGL,META,AMZN,NVDA,TSLA",
            "max_pe": 40.0,
            "sector": "Technology",
        },
        check_keys=["stocks", "passed"],
    )
    if data:
        console.print(f"     Passed: {data.get('passed')}/{data.get('total_screened')}")
        for s in (data.get("stocks") or [])[:3]:
            console.print(f"     {s['ticker']}: {s.get('market_cap')} | P/E: {s.get('pe_trailing')}")

    # 6. Compare Stocks
    data = run_test(
        "compare_stocks – NVDA vs AMD vs INTC (1y)",
        compare_stocks,
        {"tickers": "NVDA,AMD,INTC", "period": "1y"},
        check_keys=["comparison", "period"],
    )
    if data:
        console.print(f"     Performance rank: {data.get('performance_rank')}")

    # 7. Portfolio Metrics
    data = run_test(
        "calculate_portfolio_metrics – Equal weight AAPL/MSFT/GOOGL",
        calculate_portfolio_metrics,
        {
            "holdings": '[{"ticker":"AAPL","weight":0.33},{"ticker":"MSFT","weight":0.33},{"ticker":"GOOGL","weight":0.34}]',
            "period": "1y",
        },
        check_keys=["portfolio_metrics", "positions"],
    )
    if data:
        pm = data.get("portfolio_metrics", {})
        console.print(f"     Return: {pm.get('total_return')} | Sharpe: {pm.get('sharpe_ratio')} | MaxDD: {pm.get('max_drawdown')}")

    # ── Summary ───────────────────────────────────────────────────────────────
    total = TESTS_PASSED + TESTS_FAILED
    console.print()
    console.print(Rule("[bold]Test Summary[/bold]"))
    color = "green" if TESTS_FAILED == 0 else "yellow"
    console.print(f"[{color}]  Passed: {TESTS_PASSED}/{total}  |  Failed: {TESTS_FAILED}/{total}[/{color}]")
    console.print()

    if TESTS_FAILED == 0:
        console.print("[bold green]🎉 All tests passed! Skills are ready.[/bold green]")
    else:
        console.print("[bold yellow]⚠ Some tests failed. Check network connectivity and API keys.[/bold yellow]")

    return TESTS_FAILED == 0


if __name__ == "__main__":
    success = test_all()
    sys.exit(0 if success else 1)
