"""
End-to-end test for MCP + RAG tools (no LLM call needed).
Tests:
  1. MCP: get_economic_indicators (yfinance fallback)
  2. MCP: get_sec_filing_summary (SEC EDGAR, no key needed)
  3. RAG: search_investment_knowledge (requires vectorization on first run)
  4. RAG: search_market_history
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel

console = Console()

# ── Test 1: MCP – Economic Indicators ────────────────────────────────────────
console.rule("[bold cyan]TEST 1: MCP – Economic Indicators[/bold cyan]")
try:
    from mcp_server import _get_economic_indicators
    result = _get_economic_indicators("fed_rate,treasury_10y,treasury_2y")
    console.print(f"  [green]✓ source:[/green] {result['source']}")
    for k, v in result.items():
        if isinstance(v, dict) and "value" in v:
            console.print(f"  {k}: {v['value']}{v['unit']}")
except Exception as e:
    console.print(f"  [red]✗ {e}[/red]")

# ── Test 2: MCP – SEC EDGAR ───────────────────────────────────────────────────
console.rule("[bold cyan]TEST 2: MCP – SEC EDGAR 10-K (AAPL)[/bold cyan]")
try:
    from mcp_server import _get_sec_filing_summary
    result = _get_sec_filing_summary("AAPL", "10-K")
    if "error" in result:
        console.print(f"  [red]✗ {result['error']}[/red]")
    else:
        latest = result["latest_filing"]
        console.print(f"  [green]✓[/green] {result['company_name']} | CIK: {result['cik']}")
        console.print(f"  Latest 10-K: {latest['filing_date']}")
        console.print(f"  Document: {latest['document_url'][:80]}...")
except Exception as e:
    console.print(f"  [red]✗ {e}[/red]")

# ── Test 3: RAG – Investment Knowledge ───────────────────────────────────────
console.rule("[bold cyan]TEST 3: RAG – Investment Knowledge[/bold cyan]")
try:
    from rag_tools import search_investment_knowledge
    result = search_investment_knowledge.invoke({"query": "What is margin of safety in value investing?"})
    data = json.loads(result)
    if "error" in data:
        console.print(f"  [yellow]⚠ {data['error']}[/yellow]")
    else:
        console.print(f"  [green]✓ {data['num_results']} results found[/green]")
        for r in data["results"][:2]:
            console.print(f"  [{r['rank']}] {r['source']}: {r['content'][:120]}...")
except Exception as e:
    console.print(f"  [red]✗ {e}[/red]")

# ── Test 4: RAG – Market History ──────────────────────────────────────────────
console.rule("[bold cyan]TEST 4: RAG – Market History[/bold cyan]")
try:
    from rag_tools import search_market_history
    result = search_market_history.invoke({"query": "What triggered the 2008 financial crisis?"})
    data = json.loads(result)
    if "error" in data:
        console.print(f"  [yellow]⚠ {data['error']}[/yellow]")
    else:
        console.print(f"  [green]✓ {data['num_results']} results found[/green]")
        for r in data["results"][:2]:
            console.print(f"  [{r['rank']}] {r['source']}: {r['content'][:120]}...")
except Exception as e:
    console.print(f"  [red]✗ {e}[/red]")

console.rule("[bold green]All Tests Complete[/bold green]")
