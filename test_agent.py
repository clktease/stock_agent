import asyncio
from agent import build_agent
from rich.console import Console
from langchain_core.callbacks import AsyncCallbackHandler
from typing import Any

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
        
        # Try to parse input_str to extract clean arguments
        try:
            import json
            args = json.loads(input_str)
        except Exception:
            args = input_str

        if tool_name == "task":
            # Intercept sub-agent execution
            subagent = "unknown"
            task_desc = ""
            if isinstance(args, dict):
                subagent = args.get("subagent_type", args.get("subagent", "unknown"))
                task_desc = args.get("query") or args.get("description") or args.get("task") or str(args)
            else:
                subagent = str(args)
            
            self.console.print(f"\n[bold magenta]🤖 [Sub-agent] Delegating to Sub-agent: '{subagent}'[/bold magenta]")
            if task_desc:
                self.console.print(f"   [dim]Instruction: {task_desc}[/dim]")
        else:
            # Intercept general tool execution
            self.console.print(f"\n[bold green]🔧 [Tool] Calling Tool: '{tool_name}'[/bold green]")
            if isinstance(args, dict):
                args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                self.console.print(f"   [dim]Args: {args_str}[/dim]")
            else:
                self.console.print(f"   [dim]Args: {args}[/dim]")

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        pass

async def main():
    agent = await build_agent()
    tracker = AgentExecutionTracker(console)
    # Run a complex query that uses both tools and sub-agents
    query = "Do a comprehensive technical analysis of AAPL"
    console.print(f"Running query: {query}\n")
    res = await agent.ainvoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"callbacks": [tracker]}
    )
    print("\n--- DONE ---")

if __name__ == "__main__":
    asyncio.run(main())
