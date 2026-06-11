"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              Stock Analysis Deep Agent – Main Entry Point                    ║
║                                                                              ║
║  Architecture:                                                               ║
║  ┌─────────────────────────────────────────────────────────┐                 ║
║  │               Stock Analysis Deep Agent                  │                 ║
║  │  (orchestrator – plans & delegates)                      │                 ║
║  │                                                          │                 ║
║  │  ┌────────────────┐  ┌────────────────┐  ┌──────────┐  │                 ║
║  │  │Technical Analyst│  │Fundamental     │  │News &    │  │                 ║
║  │  │  Sub-agent      │  │Analyst Sub-agt │  │Sentiment │  │                 ║
║  │  └────────────────┘  └────────────────┘  └──────────┘  │                 ║
║  └─────────────────────────────────────────────────────────┘                 ║
║       +                                                                      ║
║  MCP Server (stock-analysis-mcp) – optional external tool bridge             ║
╚══════════════════════════════════════════════════════════════════════════════╝

Usage:
    python agent.py                    # Interactive CLI
    python agent.py --query "..."      # Single query mode
    python agent.py --with-mcp        # Also load tools from local MCP server
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Optional
from langchain_core.callbacks import AsyncCallbackHandler

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

# ── Load environment variables ─────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

# ── Imports after env is loaded ───────────────────────────────────────────────
from deepagents import create_deep_agent
from skills import ALL_SKILLS
from rag_tools import RAG_TOOLS, preload_vectorstores, search_investment_knowledge, search_market_history

console = Console()


class AgentExecutionTracker(AsyncCallbackHandler):
    def __init__(self, console):
        super().__init__()
        self.console = console

    async def on_tool_start(
        self,
        serialized: dict,
        input_str: str,
        *,
        run_id,
        parent_run_id=None,
        tags=None,
        metadata=None,
        **kwargs,
    ) -> None:
        tool_name = serialized.get("name", "unknown")
        
        # Try parsing input_str safely
        args = input_str
        try:
            import ast
            args = ast.literal_eval(input_str)
        except Exception:
            try:
                import json
                args = json.loads(input_str)
            except Exception:
                pass

        if tool_name == "task":
            # Sub-agent invocation
            subagent = "unknown"
            task_desc = ""
            if isinstance(args, dict):
                subagent = args.get("subagent_type", args.get("subagent", "unknown"))
                task_desc = args.get("query") or args.get("description") or args.get("task") or ""
            else:
                subagent = str(args)
            
            output = [
                f"\n[bold magenta]🤖 [Sub-agent] Delegating to Sub-agent: '{subagent}'[/bold magenta]"
            ]
            if task_desc:
                output.append(f"   [dim]Instruction: {task_desc}[/dim]")
            self.console.print("\n".join(output))
        else:
            # Regular tool call
            output = [
                f"\n[bold green]🔧 [Tool] Calling Tool: '{tool_name}'[/bold green]"
            ]
            if isinstance(args, dict):
                args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                output.append(f"   [dim]Args: {args_str}[/dim]")
            elif isinstance(args, str) and args.strip():
                output.append(f"   [dim]Args: {args.strip()}[/dim]")
            elif args:
                output.append(f"   [dim]Args: {args}[/dim]")
            self.console.print("\n".join(output))



# ─────────────────────────────────────────────────────────────────────────────
# Sub-agent definitions
# ─────────────────────────────────────────────────────────────────────────────

TECHNICAL_ANALYST_SUBAGENT = {
    "name": "technical-analyst",
    "description": (
        "A specialist in technical analysis. Use this sub-agent when you need to: "
        "analyze price charts, compute moving averages, RSI, MACD, Bollinger Bands, "
        "ATR, volume trends, or generate technical buy/sell signals for a stock."
    ),
    "system_prompt": (
        "You are an expert technical analyst with 15+ years of experience in equity markets. "
        "Your job is to analyze stock price data and technical indicators to generate clear, "
        "actionable insights. When analyzing a stock:\n"
        "1. Always check price vs SMA20/50/200 to determine trend direction.\n"
        "2. Use RSI to gauge momentum and overbought/oversold conditions.\n"
        "3. Use MACD for trend confirmation and divergence signals.\n"
        "4. Use Bollinger Bands to assess volatility and potential mean-reversion.\n"
        "5. Conclude with a clear technical outlook: Bullish / Bearish / Neutral and key levels.\n"
        "Be precise with numbers. Always state your confidence level."
    ),
}

FUNDAMENTAL_ANALYST_SUBAGENT = {
    "name": "fundamental-analyst",
    "description": (
        "A specialist in fundamental analysis. Use this sub-agent when you need to: "
        "evaluate a company's financial health, analyze valuation ratios (P/E, PEG, P/B), "
        "assess profitability, growth, dividends, balance sheet, or compare analyst targets."
    ),
    "system_prompt": (
        "You are an expert fundamental analyst (CFA charterholder equivalent). "
        "Your job is to evaluate stocks based on financial metrics and business quality. "
        "When analyzing a stock:\n"
        "1. Assess valuation: Is the stock cheap, fairly priced, or expensive vs peers?\n"
        "2. Evaluate profitability: Are margins expanding or contracting?\n"
        "3. Check growth trajectory: Revenue and earnings growth rates.\n"
        "4. Review balance sheet health: Debt levels, cash flow generation.\n"
        "5. Provide a fundamental rating: Undervalued / Fair Value / Overvalued with reasoning.\n"
        "Always provide context about the company's industry and competitive position."
    ),
}

NEWS_SENTIMENT_SUBAGENT = {
    "name": "news-sentiment-analyst",
    "description": (
        "A specialist in news analysis and market sentiment. Use this sub-agent when you need to: "
        "search for recent news about a company or sector, assess market sentiment, "
        "identify catalysts (earnings, product launches, regulatory events), or gauge "
        "overall market mood."
    ),
    "system_prompt": (
        "You are an expert market analyst specializing in news and sentiment analysis. "
        "Your job is to:\n"
        "1. Search for recent news and events affecting the stock or sector.\n"
        "2. Identify key catalysts: upcoming earnings, product releases, regulatory decisions.\n"
        "3. Assess overall market sentiment: Bullish / Bearish / Mixed.\n"
        "4. Highlight any risks or red flags mentioned in recent news.\n"
        "5. Summarize your findings in a concise market intelligence report.\n"
        "Focus on facts. Distinguish between confirmed news and speculation."
    ),
}

PORTFOLIO_MANAGER_SUBAGENT = {
    "name": "portfolio-manager",
    "description": (
        "A specialist in portfolio construction and risk management. Use this sub-agent when: "
        "comparing multiple stocks, constructing or evaluating a portfolio, calculating "
        "risk metrics (Sharpe ratio, max drawdown, volatility), or providing allocation recommendations."
    ),
    "system_prompt": (
        "You are an expert portfolio manager with deep expertise in risk-adjusted returns. "
        "Your job is to:\n"
        "1. Compare stocks and identify the best risk/reward opportunities.\n"
        "2. Calculate and interpret portfolio metrics (return, volatility, Sharpe, max drawdown).\n"
        "3. Suggest optimal position sizing and diversification strategies.\n"
        "4. Identify concentration risks and correlation issues.\n"
        "5. Provide a clear portfolio recommendation with entry/exit levels.\n"
        "Always consider both upside potential and downside risk. Think in terms of risk-adjusted returns."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# System prompt for the orchestrator
# ─────────────────────────────────────────────────────────────────────────────

ORCHESTRATOR_SYSTEM_PROMPT = """
You are a senior investment research director and chief stock analyst with deep expertise 
in global equity markets. You orchestrate a team of specialist analysts to provide 
comprehensive, actionable stock analysis.

## Your Capabilities
You have access to:
1. **Skills (direct tools)**: Price data, technical indicators, fundamentals, stock screener, 
   comparison, and portfolio metrics – callable directly.
2. **Specialist Sub-agents**: Delegate deep-dive analysis to your team:
   - `technical-analyst`: Chart patterns, indicators, price signals
   - `fundamental-analyst`: Financial statements, valuation ratios, business quality
   - `news-sentiment-analyst`: News, catalysts, market sentiment
   - `portfolio-manager`: Multi-stock comparison, portfolio construction, risk metrics

## How to Respond
For simple queries (e.g., "What is AAPL's current price?"):
- Use direct skills/tools to answer immediately.

For comprehensive analysis requests:
1. **Gather data** using your direct skills.
2. **Delegate** to appropriate sub-agents for deep analysis.
3. **Synthesize** all findings into a structured investment report.

## Report Format
Always structure comprehensive analyses as:
```
# 📊 [Company Name] ([TICKER]) – Investment Analysis

## Executive Summary
[2-3 sentence overall assessment]

## Technical Analysis
[From technical-analyst sub-agent]

## Fundamental Analysis  
[From fundamental-analyst sub-agent]

## News & Sentiment
[From news-sentiment-analyst sub-agent]

## Investment Thesis & Recommendation
- **Rating**: BUY / HOLD / SELL
- **Target Price**: $XXX (12-month)
- **Key Risks**: ...
- **Key Catalysts**: ...
```

## Important Notes
- Always cite specific numbers and data.
- Distinguish between facts and forward-looking estimates.
- This is for educational purposes – not personalized financial advice.
- If a ticker is not found, suggest alternatives or ask for clarification.
"""


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool Loader (optional)
# ─────────────────────────────────────────────────────────────────────────────

async def load_mcp_tools_async():
    """Load tools from the local MCP server (optional integration)."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({
            "stock-analysis": {
                "command": sys.executable,
                "args": [str(Path(__file__).parent / "mcp_server.py")],
                "transport": "stdio",
            },
        })
        tools = await client.get_tools()
        console.print(f"[green]✓ Loaded {len(tools)} tools from MCP server[/green]")
        return tools
    except Exception as e:
        console.print(f"[yellow]⚠ MCP server unavailable: {e}. Using local skills only.[/yellow]")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Agent Factory
# ─────────────────────────────────────────────────────────────────────────────

async def build_agent(with_mcp: bool = False):
    """Build and return the Deep Agent instance with tiered tool architecture.

    Tool Architecture
    -----------------
    Global tools  -> Orchestrator + all sub-agents (generic / cross-cutting)
        * compare_stocks   - side-by-side multi-stock comparison
        * screen_stocks    - screener, useful in any discovery task
        * search_news      - Tavily web search (optional, if key is set)

    Skill-bound tools -> Only the sub-agent that owns that skill
        * technical-analyst    -> get_stock_price + calculate_technical_indicators
                                  + search_investment_knowledge (RAG)
        * fundamental-analyst  -> get_fundamental_data
                                  + get_sec_filing_summary (MCP) + search_investment_knowledge (RAG)
        * news-sentiment       -> search_news + get_economic_indicators (MCP)
                                  + search_market_history (RAG)
        * portfolio-manager    -> calculate_portfolio_metrics + compare_stocks
                                  + get_economic_indicators (MCP) + search_market_history (RAG)
    """
    model          = os.environ.get("AGENT_MODEL", "openai:gpt-5.2")
    subagent_model = os.environ.get("SUBAGENT_MODEL", "openai:gpt-5.2")
    skills_dir     = str(Path(__file__).parent / "skills")

    # -- Import individual skills -----------------------------------------------
    from skills import (
        get_stock_price,
        calculate_technical_indicators,
        get_fundamental_data,
        screen_stocks,
        compare_stocks,
        calculate_portfolio_metrics,
    )

    # -- Pre-build / load RAG vector indexes at startup -------------------------
    await asyncio.get_event_loop().run_in_executor(None, preload_vectorstores)

    # -- MCP-wrapped langchain tools (economic indicators + SEC filings) --------
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def get_economic_indicators(indicators: str = "all") -> str:
        """
        Fetch live macroeconomic indicators: Fed funds rate, CPI inflation, GDP
        growth rate, unemployment rate, and US Treasury yields (2Y / 10Y).
        Also computes the 2Y-10Y yield curve spread as a recession signal.

        Use this for any question about:
        - Current interest rates or Fed monetary policy
        - Inflation trends and CPI readings
        - GDP growth rate or recession risk
        - Treasury yields and yield curve shape
        - Macro context needed for sector or stock analysis

        Args:
            indicators: Comma-separated list or 'all'.
                        Options: fed_rate, cpi, gdp, unemployment, treasury_10y, treasury_2y
        Returns:
            JSON with current values and descriptions for each indicator.
        """
        import sys, json
        sys.path.insert(0, str(Path(__file__).parent))
        from mcp_server import _get_economic_indicators
        return json.dumps(_get_economic_indicators(indicators), ensure_ascii=False, default=str)

    @lc_tool
    def get_sec_filing_summary(ticker: str, form_type: str = "10-K") -> str:
        """
        Retrieve the most recent SEC regulatory filing (10-K or 10-Q) for a
        US-listed company via the free SEC EDGAR API. Returns filing dates,
        accession numbers, and direct document URLs to the actual SEC filing.

        Use this for:
        - A company's latest annual or quarterly filing
        - Risk factors in a 10-K (typically Item 1A)
        - Filing dates and EDGAR accession numbers
        - Links to official financial statements

        Args:
            ticker:    US stock ticker e.g. 'AAPL', 'TSLA', 'MSFT'
            form_type: '10-K' (annual, default) or '10-Q' (quarterly)
        Returns:
            JSON with company name, CIK, filing dates, and document URLs.
        """
        import sys, json
        sys.path.insert(0, str(Path(__file__).parent))
        from mcp_server import _get_sec_filing_summary
        return json.dumps(_get_sec_filing_summary(ticker, form_type), ensure_ascii=False, default=str)

    # -- Global tools (orchestrator + all sub-agents) ---------------------------
    global_tools: list = [compare_stocks, screen_stocks]

    if os.environ.get("TAVILY_API_KEY"):
        try:
            from langchain_community.tools.tavily_search import TavilySearchResults
            search_news = TavilySearchResults(max_results=5, name="search_news")
            global_tools.append(search_news)
            console.print("[green]✓ Tavily web search enabled[/green]")
        except ImportError:
            console.print("[yellow]⚠ tavily-python not installed. Skipping web search.[/yellow]")
            search_news = None
    else:
        search_news = None

    if with_mcp:
        mcp_tools = await load_mcp_tools_async()
        global_tools.extend(mcp_tools)


    # -- Skill-bound tool sets (per sub-agent) ----------------------------------
    technical_tools   = [get_stock_price, calculate_technical_indicators,
                         search_investment_knowledge]
    fundamental_tools = [get_fundamental_data, get_sec_filing_summary,
                         search_investment_knowledge]
    sentiment_tools   = ([search_news] if search_news else []) + [get_economic_indicators,
                         search_market_history]
    portfolio_tools   = [calculate_portfolio_metrics, compare_stocks,
                         get_economic_indicators, search_market_history]

    # -- Sub-agent configs with targeted tool sets ------------------------------
    subagents_config = [
        {
            **TECHNICAL_ANALYST_SUBAGENT,
            "model": subagent_model,
            "tools": technical_tools + global_tools,
        },
        {
            **FUNDAMENTAL_ANALYST_SUBAGENT,
            "model": subagent_model,
            "tools": fundamental_tools + global_tools,
        },
        {
            **NEWS_SENTIMENT_SUBAGENT,
            "model": subagent_model,
            "tools": sentiment_tools + global_tools,
        },
        {
            **PORTFOLIO_MANAGER_SUBAGENT,
            "model": subagent_model,
            "tools": portfolio_tools + global_tools,
        },
    ]

    # ── Orchestrator: all tools + SKILL.md directory ──────────────────────────
    orchestrator_tools = list({
        id(t): t for t in (
            [get_stock_price, calculate_technical_indicators,
             get_fundamental_data, calculate_portfolio_metrics,
             get_economic_indicators, get_sec_filing_summary,
             search_investment_knowledge, search_market_history]
            + global_tools
        )
    }.values())   # deduplicate by identity

    agent = create_deep_agent(
        model=model,
        tools=orchestrator_tools,
        skills=skills_dir,           # loads all SKILL.md files into system prompt
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        subagents=subagents_config,
    )

    console.print(f"[green]✓ Deep Agent ready (model: {model})[/green]")
    console.print(f"[dim]  Orchestrator tools: {len(orchestrator_tools)} | Sub-agents: 4[/dim]")
    console.print(f"[dim]  Skills directory: {skills_dir}[/dim]")
    console.print(
        f"[dim]  Tool allocation: "
        f"technical({len(technical_tools+global_tools)}) | "
        f"fundamental({len(fundamental_tools+global_tools)}) | "
        f"sentiment({len(sentiment_tools+global_tools)}) | "
        f"portfolio({len(portfolio_tools+global_tools)})[/dim]"
    )
    return agent



# ─────────────────────────────────────────────────────────────────────────────
# CLI Interface
# ─────────────────────────────────────────────────────────────────────────────

def print_banner():
    banner = """
    ╔══════════════════════════════════════════════════════╗
    ║        📈  Stock Analysis Deep Agent  📉             ║
    ║                                                      ║
    ║  Powered by: LangChain Deep Agents + MCP             ║
    ║  Skills: Price · Technical · Fundamental · News      ║
    ╚══════════════════════════════════════════════════════╝
    """
    console.print(Panel(banner.strip(), style="bold blue"))
    console.print()
    console.print("  [dim]Example queries:[/dim]")
    console.print("  * Analyze AAPL with full technical and fundamental analysis")
    console.print("  * Compare NVDA, AMD, and INTC over the past year")
    console.print("  * Screen stocks with P/E < 20 from: AAPL,MSFT,GOOGL,META,AMZN")
    console.print("  * Calculate portfolio metrics for AAPL 40%, MSFT 30%, GOOGL 30%")
    console.print("  * What are current Fed interest rates and CPI?  [MCP]")
    console.print("  * Show me TSLA's latest 10-K SEC filing  [MCP]")
    console.print("  * What caused the 2008 financial crisis?  [RAG]")
    console.print("  * How should I use PEG ratio to evaluate growth stocks?  [RAG]")
    console.print()
    console.print("  Type [bold]quit[/bold] or [bold]exit[/bold] to quit.\n")


def _get_message_content_str(message) -> str:
    """Extract string content from a message (object or dict) or content list."""
    if message is None:
        return ""
    
    # Extract content from message
    if hasattr(message, "content"):
        content = message.content
    elif isinstance(message, dict) and "content" in message:
        content = message["content"]
    else:
        content = message

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
            else:
                text_parts.append(str(block))
        return "\n".join(text_parts)
    return str(content)


async def run_query(agent, query: str) -> str:
    """Run a single query through the agent."""
    console.print(Rule(f"[bold]🔍 Analyzing: {query[:60]}{'…' if len(query) > 60 else ''}"))
    with console.status("[bold cyan]Agent thinking…[/bold cyan]", spinner="dots"):
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"callbacks": [AgentExecutionTracker(console)]}
        )

    # Extract final message content
    messages = result.get("messages", [])
    if messages:
        content = _get_message_content_str(messages[-1])
    else:
        content = str(result)

    return content


async def interactive_mode(agent):
    """Run the agent in interactive CLI mode."""
    print_banner()
    history = []

    while True:
        try:
            query = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye! 👋[/dim]")
            break

        if query.strip().lower() in ("quit", "exit", "q", "bye"):
            console.print("\n[dim]Goodbye! 👋[/dim]")
            break

        if not query.strip():
            continue

        history.append({"role": "user", "content": query})

        try:
            with console.status("[bold cyan]🤖 Agent is working…[/bold cyan]", spinner="dots2"):
                result = await agent.ainvoke(
                    {"messages": history},
                    config={"callbacks": [AgentExecutionTracker(console)]}
                )

            messages = result.get("messages", [])
            if messages:
                response = _get_message_content_str(messages[-1])
                history.append({"role": "assistant", "content": response})
            else:
                response = str(result)

            console.print()
            console.print(Panel(Markdown(response), title="[bold green]📊 Analysis[/bold green]", border_style="green"))

        except Exception as e:
            console.print(f"\n[red]❌ Error: {e}[/red]")
            console.print("[dim]Try again with a different query.[/dim]")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Stock Analysis Deep Agent – AI-powered equity research assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent.py
  python agent.py --query "Analyze AAPL with technical and fundamental analysis"
  python agent.py --query "Compare NVDA AMD INTC" --with-mcp
        """,
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Run a single query and exit (non-interactive mode)",
    )
    parser.add_argument(
        "--with-mcp",
        action="store_true",
        default=False,
        help="Also load tools from the local MCP server (requires mcp_server.py running)",
    )
    args = parser.parse_args()

    # Validate at least one LLM key is set
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]❌ Error: No LLM API key found.[/red]")
        console.print("Please set OPENAI_API_KEY or ANTHROPIC_API_KEY in your .env file.")
        console.print("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    agent = await build_agent(with_mcp=args.with_mcp)

    if args.query:
        # Single-query mode
        response = await run_query(agent, args.query)
        console.print()
        console.print(Panel(Markdown(response), title="[bold green]📊 Analysis[/bold green]", border_style="green"))
    else:
        # Interactive mode
        await interactive_mode(agent)


if __name__ == "__main__":
    asyncio.run(main())
