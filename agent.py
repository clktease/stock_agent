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
from influencer_tracking import (
    track_influencer, untrack_influencer, list_tracked_influencers, get_recent_statements,
)

console = Console()


class TokenUsageAccumulator:
    """Thread-safe accumulator for token usage across an agent invocation."""
    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.cache_creation_tokens: int = 0
        self.llm_calls: int = 0

    def add(self, input_tokens: int = 0, output_tokens: int = 0,
            cache_read: int = 0, cache_creation: int = 0):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read
        self.cache_creation_tokens += cache_creation
        self.llm_calls += 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# Global session-level accumulator (resets each interactive turn)
_session_tokens = TokenUsageAccumulator()


def _extract_token_counts(response_metadata: dict) -> dict:
    """
    Extract token counts from LangChain response_metadata.
    Supports OpenAI, Anthropic, and Google Gemini formats.
    """
    counts = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}

    if not response_metadata:
        return counts

    # ── Anthropic ──────────────────────────────────────────────────────────────
    usage = response_metadata.get("usage", {})
    if usage:
        counts["input"]          = usage.get("input_tokens", 0)
        counts["output"]         = usage.get("output_tokens", 0)
        counts["cache_read"]     = usage.get("cache_read_input_tokens", 0)
        counts["cache_creation"] = usage.get("cache_creation_input_tokens", 0)
        if any(counts.values()):
            return counts

    # ── OpenAI ─────────────────────────────────────────────────────────────────
    token_usage = response_metadata.get("token_usage", {})
    if token_usage:
        counts["input"]      = token_usage.get("prompt_tokens", 0)
        counts["output"]     = token_usage.get("completion_tokens", 0)
        # OpenAI prompt_tokens_details for cached tokens
        details = token_usage.get("prompt_tokens_details") or {}
        counts["cache_read"] = details.get("cached_tokens", 0)
        if any(counts.values()):
            return counts

    # ── Google Gemini ──────────────────────────────────────────────────────────
    counts["input"]  = response_metadata.get("prompt_token_count", 0)
    counts["output"] = response_metadata.get("candidates_token_count", 0)
    counts["cache_read"] = response_metadata.get("cached_content_token_count", 0)

    return counts


class AgentExecutionTracker(AsyncCallbackHandler):
    def __init__(self, console, accumulator: "TokenUsageAccumulator | None" = None):
        super().__init__()
        self.console = console
        self.accumulator = accumulator  # optional per-invocation accumulator

    # ── Token tracking callbacks ───────────────────────────────────────────────

    async def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs) -> None:
        """Called after every LLM call (non-streaming or streaming finish)."""
        try:
            # LLMResult → generations[0][0].generation_info or response.llm_output
            llm_output = getattr(response, "llm_output", {}) or {}
            metadata = llm_output.get("token_usage") or llm_output.get("usage") or {}

            combined = {}
            if hasattr(response, "generations") and response.generations:
                gen0 = response.generations[0]
                if gen0:
                    g = gen0[0]
                    msg_obj = getattr(g, "message", None)
                    if msg_obj:
                        resp_meta = getattr(msg_obj, "response_metadata", None) or {}
                        combined.update(resp_meta)
                        usage_meta = getattr(msg_obj, "usage_metadata", None) or {}
                        if usage_meta:
                            combined["usage"] = {
                                "input_tokens":  usage_meta.get("input_tokens", 0),
                                "output_tokens": usage_meta.get("output_tokens", 0),
                                "cache_read_input_tokens":     usage_meta.get("input_token_details", {}).get("cache_read", 0),
                                "cache_creation_input_tokens": usage_meta.get("input_token_details", {}).get("cache_creation", 0),
                            }
                    else:
                        gen_meta = getattr(g, "generation_info", None) or {}
                        if isinstance(gen_meta, dict):
                            combined.update(gen_meta)

            combined.update(llm_output)
            if metadata:
                combined["token_usage"] = metadata

            counts = _extract_token_counts(combined)
            self._print_and_accumulate(counts)
        except Exception:
            pass  # never break the agent on token-tracking errors

    async def on_chat_model_end(self, response, *, run_id, parent_run_id=None, **kwargs) -> None:
        """Called after every chat model call – preferred path for most providers."""
        try:
            meta = {}
            if hasattr(response, "generations") and response.generations:
                gen0 = response.generations[0]
                if gen0:
                    msg = getattr(gen0[0], "message", None)
                    if msg:
                        meta = getattr(msg, "response_metadata", None) or {}
                        usage_meta = getattr(msg, "usage_metadata", None) or {}
                        if usage_meta:
                            meta["usage"] = {
                                "input_tokens":  usage_meta.get("input_tokens", 0),
                                "output_tokens": usage_meta.get("output_tokens", 0),
                                "cache_read_input_tokens":     usage_meta.get("input_token_details", {}).get("cache_read", 0),
                                "cache_creation_input_tokens": usage_meta.get("input_token_details", {}).get("cache_creation", 0),
                            }
            if not meta:
                llm_output = getattr(response, "llm_output", {}) or {}
                meta = llm_output
            counts = _extract_token_counts(meta)
            self._print_and_accumulate(counts)
        except Exception:
            pass

    def _print_and_accumulate(self, counts: dict) -> None:
        """Print per-call token stats and accumulate into session totals."""
        inp   = counts["input"]
        out   = counts["output"]
        cache = counts["cache_read"]
        ccr   = counts["cache_creation"]

        if inp == 0 and out == 0:
            return  # no meaningful data – skip

        parts = [
            f"[cyan]input={inp:,}[/cyan]",
            f"[green]output={out:,}[/green]",
        ]
        if cache:
            parts.append(f"[yellow]cache_read={cache:,}[/yellow]")
        if ccr:
            parts.append(f"[dim]cache_write={ccr:,}[/dim]")

        self.console.print(
            f"\n[dim]📊 Tokens:[/dim] " + "  ".join(parts)
        )

        # Accumulate
        if self.accumulator is not None:
            self.accumulator.add(inp, out, cache, ccr)
        _session_tokens.add(inp, out, cache, ccr)

    # ── Tool tracking callbacks (unchanged) ───────────────────────────────────

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
        "Be precise with numbers. Always state your confidence level.\n"
        "6. Always respond in the same language as the incoming query/instruction (e.g. if the user asks or delegates in Traditional Chinese, reply in Traditional Chinese)."
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
        "Always provide context about the company's industry and competitive position.\n"
        "6. Always respond in the same language as the incoming query/instruction (e.g. if the user asks or delegates in Traditional Chinese, reply in Traditional Chinese)."
    ),
}

NEWS_SENTIMENT_SUBAGENT = {
    "name": "news-sentiment-analyst",
    "description": (
        "A specialist in news analysis and market sentiment. Use this sub-agent when you need to: "
        "search for recent news about a company or sector, assess market sentiment, "
        "identify catalysts (earnings, product launches, regulatory events), gauge "
        "overall market mood, or analyze whether a public figure's/influencer's recent "
        "statement or social media post has investment-relevant implications."
    ),
    "system_prompt": (
        "You are an expert market analyst specializing in news and sentiment analysis. "
        "Your job is to:\n"
        "1. Search for recent news and events affecting the stock or sector.\n"
        "2. Identify key catalysts: upcoming earnings, product releases, regulatory decisions.\n"
        "3. Assess overall market sentiment: Bullish / Bearish / Mixed.\n"
        "4. Highlight any risks or red flags mentioned in recent news.\n"
        "5. Summarize your findings in a concise market intelligence report.\n"
        "Focus on facts. Distinguish between confirmed news and speculation.\n"
        "6. When analyzing a public figure's/influencer's statement or social post (via "
        "get_recent_statements or a tracked-influencer alert), clearly separate confirmed direct "
        "quotes from media interpretation, only assert investment relevance when it is genuinely "
        "clear (say so plainly when it isn't), and always flag that single-statement-driven signals "
        "can be noisy, unverified, or manipulated (e.g. meme-stock dynamics) — never treat one "
        "person's post as guaranteed market-moving on its own.\n"
        "7. Always respond in the same language as the incoming query/instruction (e.g. if the user asks or delegates in Traditional Chinese, reply in Traditional Chinese)."
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
        "Always consider both upside potential and downside risk. Think in terms of risk-adjusted returns.\n"
        "6. Always respond in the same language as the incoming query/instruction (e.g. if the user asks or delegates in Traditional Chinese, reply in Traditional Chinese)."
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
   - `news-sentiment-analyst`: News, catalysts, market sentiment, and influencer/public-figure statement analysis
   - `portfolio-manager`: Multi-stock comparison, portfolio construction, risk metrics
3. **Influencer Tracking**: Use `track_influencer` / `untrack_influencer` / `list_tracked_influencers`
   directly (no need to delegate) when the user wants to start/stop/list background monitoring of a
   public figure's statements. Use `get_recent_statements` for one-off questions about what someone
   has recently said, or delegate to `news-sentiment-analyst` for a deeper investment-relevance analysis.

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

## Language Consistency (CRITICAL)
- You MUST respond in the same language as the user's input/query. If the user asks in Traditional Chinese (繁體中文), your entire response, including all headers, tables, analyses, summaries, and recommendations, must be in Traditional Chinese.
- Delegate tasks to sub-agents in the same language as the user's query if possible, and translate any insights, terminology, or data retrieved from tools or sub-agents (e.g. English text) into the user's query language in the final report.

## Important Notes
- Always cite specific numbers and data.
- Distinguish between facts and forward-looking estimates.
- This is for educational purposes – not personalized financial advice.
- Use the `ask_clarification` tool to ask for clarification when a query is ambiguous, e.g. when the user asks to analyze the "stock market" (分析股市) but does not specify whether they want US stocks (美股), Taiwan stocks (台股), or Korean stocks (韓股).
- If a ticker is not found, suggest alternatives or ask for clarification.
- When analysis is triggered by a single public figure's/influencer's statement or social media post
  (whether from `get_recent_statements`, a tracked-influencer background alert, or a direct user
  question about what someone said), always flag that single-statement-driven signals can be noisy,
  unverified, or subject to manipulation (e.g. meme-stock dynamics) — do not present them as
  guaranteed market-moving events, and explicitly say so when there is no clear investment relevance.
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


from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

@tool
def ask_clarification(question: str, options: list[str]) -> str:
    """
    Ask the user a clarifying question when the query is ambiguous or needs user input/choice.
    Use this tool to ask for clarification, e.g. when the user asks to analyze 'stock market'
    but doesn't specify which market (e.g., US stocks, Taiwan stocks, Korean stocks), or when
    multiple choices are possible.
    
    Args:
        question: The question to display to the user.
        options: A list of options for the user to choose from.
    Returns:
        The option selected by the user.
    """
    return "This return value is a placeholder; it will be overwritten by human response."


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
    from langchain.chat_models import init_chat_model
    from deepagents.profiles.provider.provider_profiles import apply_provider_profile

    model_name = os.environ.get("AGENT_MODEL", "openai:gpt-5.2")
    subagent_model_name = os.environ.get("SUBAGENT_MODEL", "openai:gpt-5.2")

    model = init_chat_model(model_name, streaming=True, **apply_provider_profile(model_name))
    subagent_model = init_chat_model(subagent_model_name, streaming=True, **apply_provider_profile(subagent_model_name))
    skills_dir     = str(Path(__file__).parent / "skills")

    # -- Import individual skills -----------------------------------------------
    from skills import (
        get_stock_price,
        calculate_technical_indicators,
        get_fundamental_data,
        screen_stocks,
        compare_stocks,
        calculate_portfolio_metrics,
        read_holdings_csv,
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
    global_tools: list = [
        compare_stocks, screen_stocks, ask_clarification,
        track_influencer, untrack_influencer, list_tracked_influencers,
    ]

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
                         search_market_history, get_recent_statements]
    portfolio_tools   = [calculate_portfolio_metrics, compare_stocks,
                         get_economic_indicators, search_market_history,
                         read_holdings_csv]

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
             search_investment_knowledge, search_market_history,
             read_holdings_csv, get_recent_statements]
            + global_tools
        )
    }.values())   # deduplicate by identity

    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=model,
        tools=orchestrator_tools,
        skills=skills_dir,           # loads all SKILL.md files into system prompt
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        subagents=subagents_config,
        checkpointer=checkpointer,
        interrupt_on={"ask_clarification": True},
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


async def run_query(agent, query: str) -> tuple[str, TokenUsageAccumulator]:
    """Run a single query through the agent."""
    console.print(Rule(f"[bold]🔍 Analyzing: {query[:60]}{'…' if len(query) > 60 else ''}"))
    turn_acc = TokenUsageAccumulator()
    with console.status("[bold cyan]Agent thinking…[/bold cyan]", spinner="dots"):
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"callbacks": [AgentExecutionTracker(console, accumulator=turn_acc)]}
        )

    # Extract final message content
    messages = result.get("messages", [])
    if messages:
        content = _get_message_content_str(messages[-1])
    else:
        content = str(result)

    return content, turn_acc


def _print_token_summary(acc: "TokenUsageAccumulator", label: str = "Turn") -> None:
    """Print a formatted token-usage summary box."""
    if acc.llm_calls == 0:
        return
    lines = [
        f"  [bold]LLM calls :[/bold] {acc.llm_calls}",
        f"  [bold cyan]Input     :[/bold cyan] {acc.input_tokens:,} tokens",
        f"  [bold green]Output    :[/bold green] {acc.output_tokens:,} tokens",
    ]
    if acc.cache_read_tokens:
        lines.append(f"  [bold yellow]Cache read:[/bold yellow] {acc.cache_read_tokens:,} tokens")
    if acc.cache_creation_tokens:
        lines.append(f"  [dim]Cache write: {acc.cache_creation_tokens:,} tokens[/dim]")
    lines.append(f"  [bold]Total     :[/bold] {acc.total_tokens:,} tokens")
    console.print(
        Panel("\n".join(lines),
              title=f"[bold white]📊 Token Usage – {label}[/bold white]",
              border_style="blue",
              padding=(0, 1))
    )


async def interactive_mode(agent):
    """Run the agent in interactive CLI mode."""
    print_banner()
    history = []

    while True:
        try:
            query = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            _print_token_summary(_session_tokens, label="Session Total")
            console.print("\n[dim]Goodbye! 👋[/dim]")
            break

        if query.strip().lower() in ("quit", "exit", "q", "bye"):
            _print_token_summary(_session_tokens, label="Session Total")
            console.print("\n[dim]Goodbye! 👋[/dim]")
            break

        if not query.strip():
            continue

        history.append({"role": "user", "content": query})

        try:
            turn_acc = TokenUsageAccumulator()
            with console.status("[bold cyan]🤖 Agent is working…[/bold cyan]", spinner="dots2"):
                result = await agent.ainvoke(
                    {"messages": history},
                    config={"callbacks": [AgentExecutionTracker(console, accumulator=turn_acc)]}
                )

            messages = result.get("messages", [])
            if messages:
                response = _get_message_content_str(messages[-1])
                history.append({"role": "assistant", "content": response})
            else:
                response = str(result)

            console.print()
            console.print(Panel(Markdown(response), title="[bold green]📊 Analysis[/bold green]", border_style="green"))

            # ── Per-turn token summary ──────────────────────────────────────
            _print_token_summary(turn_acc, label="This Request")

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
        response, turn_acc = await run_query(agent, args.query)
        console.print()
        console.print(Panel(Markdown(response), title="[bold green]📊 Analysis[/bold green]", border_style="green"))
        _print_token_summary(turn_acc, label="This request")
    else:
        # Interactive mode
        await interactive_mode(agent)


if __name__ == "__main__":
    asyncio.run(main())
