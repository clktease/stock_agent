"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         Stock Analysis Deep Agent — FastAPI WebSocket Backend                ║
║                                                                              ║
║  Serves the web UI and bridges browser queries to the Deep Agent via         ║
║  WebSocket, streaming tool-call events in real time.                         ║
║                                                                              ║
║  Usage:                                                                      ║
║    python web_server.py                                                      ║
║    open http://localhost:8000                                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import ast
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import AsyncCallbackHandler

load_dotenv(Path(__file__).parent / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# Tool Layer Classification
# ─────────────────────────────────────────────────────────────────────────────

SKILL_TOOLS = {
    "get_stock_price",
    "calculate_technical_indicators",
    "get_fundamental_data",
    "compare_stocks",
    "screen_stocks",
    "calculate_portfolio_metrics",
    "get_market_overview",
    "search_news",
}
MCP_TOOLS = {
    "get_economic_indicators",
    "get_sec_filing_summary",
}
RAG_TOOLS_SET = {
    "search_investment_knowledge",
    "search_market_history",
}

# ─────────────────────────────────────────────────────────────────────────────
# Session Manager
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    session_id: str
    messages: List[Tuple[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


class SessionManager:
    """Stores per-session conversation history (in-memory, LRU-like)."""
    MAX_HISTORY_PAIRS = 15   # keep last N human/ai pairs per session
    MAX_SESSIONS = 100       # evict oldest if over limit

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def new_session(self) -> Session:
        self._evict_if_needed()
        sid = str(uuid.uuid4())
        s = Session(session_id=sid)
        self._sessions[sid] = s
        return s

    def reset(self, session_id: str) -> Session:
        """Keep same ID, clear history."""
        s = Session(session_id=session_id)
        self._sessions[session_id] = s
        return s

    def add_exchange(self, session_id: str, human_msg: str, ai_msg: str) -> None:
        s = self._sessions.get(session_id)
        if not s:
            return
        s.messages.append(("human", human_msg))
        s.messages.append(("ai",    ai_msg))
        s.last_active = time.time()
        # Trim to MAX_HISTORY_PAIRS * 2 messages
        max_msgs = self.MAX_HISTORY_PAIRS * 2
        if len(s.messages) > max_msgs:
            s.messages = s.messages[-max_msgs:]

    def get_messages(self, session_id: str) -> List[Tuple[str, str]]:
        s = self._sessions.get(session_id)
        return list(s.messages) if s else []

    def _evict_if_needed(self) -> None:
        if len(self._sessions) >= self.MAX_SESSIONS:
            # Remove the least-recently-active session
            oldest = min(self._sessions.values(), key=lambda s: s.last_active)
            del self._sessions[oldest.session_id]


session_manager = SessionManager()


def classify_tool(name: str) -> str:
    if name == "task":
        return "SUBAGENT"
    if name in MCP_TOOLS:
        return "MCP"
    if name in RAG_TOOLS_SET:
        return "RAG"
    return "SKILL"


def _parse_args(input_str: str) -> dict:
    try:
        val = ast.literal_eval(input_str)
        return val if isinstance(val, dict) else {"input": str(val)[:200]}
    except Exception:
        pass
    try:
        val = json.loads(input_str)
        return val if isinstance(val, dict) else {"input": str(val)[:200]}
    except Exception:
        pass
    return {"input": str(input_str)[:200]}


def _args_summary(tool_name: str, args: dict) -> str:
    """Return a short one-line summary of the tool call arguments."""
    if tool_name == "task":
        return args.get("subagent_type", args.get("subagent", ""))
    vals = [str(v) for v in args.values() if v and str(v).strip()]
    return vals[0][:80] if vals else ""


def extract_clean_text(val) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        stripped = val.strip()
        if (stripped.startswith("[") and stripped.endswith("]")) or (stripped.startswith("{") and stripped.endswith("}")):
            try:
                parsed = ast.literal_eval(stripped)
                return extract_clean_text(parsed)
            except Exception:
                try:
                    parsed = json.loads(stripped)
                    return extract_clean_text(parsed)
                except Exception:
                    pass
        return val
    if isinstance(val, list):
        return "".join(extract_clean_text(item) for item in val)
    if isinstance(val, dict):
        if val.get("type") == "text" or "text" in val:
            return extract_clean_text(val.get("text", ""))
        if "content" in val:
            return extract_clean_text(val.get("content", ""))
        return ""
    return str(val)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Callback Handler
# ─────────────────────────────────────────────────────────────────────────────

class WebSocketCallbackHandler(AsyncCallbackHandler):
    """Intercepts Deep Agent tool calls and streams events to the browser."""

    def __init__(self, ws: WebSocket):
        super().__init__()
        self.ws = ws
        self._run_start: dict[str, float] = {}
        self._tool_descendants: set[str] = set()
        from agent import TokenUsageAccumulator
        self.accumulator = TokenUsageAccumulator()

    async def _send(self, payload: dict) -> None:
        try:
            await self.ws.send_json(payload)
        except Exception:
            pass

    async def on_chain_start(
        self,
        serialized: dict,
        inputs: dict,
        *,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        rid = str(run_id)
        pid = str(parent_run_id) if parent_run_id else None
        if pid in self._run_start or pid in self._tool_descendants:
            self._tool_descendants.add(rid)

    async def on_llm_start(
        self,
        serialized: dict,
        prompts: list,
        *,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        rid = str(run_id)
        pid = str(parent_run_id) if parent_run_id else None
        if pid in self._run_start or pid in self._tool_descendants:
            self._tool_descendants.add(rid)

    async def on_llm_new_token(
        self,
        token: Any,
        *,
        chunk=None,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        rid = str(run_id)
        pid = str(parent_run_id) if parent_run_id else None
        if pid in self._run_start or pid in self._tool_descendants or rid in self._tool_descendants:
            return

        # Check if this chunk is generating a tool call
        if chunk is not None:
            msg = getattr(chunk, "message", chunk)
            if getattr(msg, "tool_call_chunks", None):
                return
            add_kwargs = getattr(msg, "additional_kwargs", {})
            if add_kwargs and "tool_calls" in add_kwargs:
                return

        # Extract underlying content if it is an object
        raw_val = token
        if hasattr(token, "content"):
            raw_val = token.content

        # Extract text content from token robustly (handles raw strings, dicts, lists, JSON content blocks)
        content_str = extract_clean_text(raw_val)

        if not content_str:
            return

        # Double check if content_str looks like a JSON tool call
        stripped = content_str.strip()
        if stripped.startswith('{"tool_calls"') or stripped.startswith('{"name": "task"'):
            return

        await self._send({"type": "token", "content": content_str})

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
        layer = classify_tool(tool_name)
        args = _parse_args(input_str)
        summary = _args_summary(tool_name, args)
        rid = str(run_id)
        self._run_start[rid] = time.time()

        await self._send(
            {
                "type": "tool_call",
                "tool": tool_name,
                "layer": layer,
                "args": {k: str(v)[:120] for k, v in args.items()},
                "summary": summary,
                "run_id": rid,
            }
        )

    async def on_tool_end(self, output, *, run_id, **kwargs) -> None:
        rid = str(run_id)
        t0 = self._run_start.get(rid)
        elapsed_ms = round((time.time() - t0) * 1000) if t0 else 0
        await self._send({"type": "tool_done", "run_id": rid, "elapsed_ms": elapsed_ms})

    async def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs) -> None:
        try:
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

            from agent import _extract_token_counts
            counts = _extract_token_counts(combined)
            inp = counts["input"]
            out = counts["output"]
            cache = counts["cache_read"]
            ccr = counts["cache_creation"]
            if inp > 0 or out > 0:
                self.accumulator.add(inp, out, cache, ccr)
                print(f"[Tokens] Call input={inp}, output={out}, cache={cache} | Acc input={self.accumulator.input_tokens}, output={self.accumulator.output_tokens}")
        except Exception:
            pass

    async def on_chat_model_end(self, response, *, run_id, parent_run_id=None, **kwargs) -> None:
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
            
            from agent import _extract_token_counts
            counts = _extract_token_counts(meta)
            inp = counts["input"]
            out = counts["output"]
            cache = counts["cache_read"]
            ccr = counts["cache_creation"]
            if inp > 0 or out > 0:
                self.accumulator.add(inp, out, cache, ccr)
                print(f"[Tokens] Chat input={inp}, output={out}, cache={cache} | Acc input={self.accumulator.input_tokens}, output={self.accumulator.output_tokens}")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Agent Singleton (built once on startup)
# ─────────────────────────────────────────────────────────────────────────────

_agent = None


async def _get_agent():
    global _agent
    if _agent is None:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from agent import build_agent
        _agent = await build_agent()
    return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("⚙  Pre-warming Deep Agent…")
    try:
        await _get_agent()
        print("✓  Agent ready")
    except Exception as e:
        print(f"⚠  Agent warm-up failed (will retry on first request): {e}")
    yield


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Stock Analysis Deep Agent", lifespan=lifespan)

_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
async def index():
    html_path = _static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h2>UI not found — make sure static/index.html exists.</h2>",
        status_code=404,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "agent_ready": _agent is not None}


_uploads_dir = Path(__file__).parent / "uploads"
_uploads_dir.mkdir(exist_ok=True)


@app.post("/upload")
async def upload_holdings(file: UploadFile = File(...), session_id: str = "default"):
    if not file.filename.endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Only CSV files are supported."})
    
    try:
        filename = f"holdings_{session_id}.csv"
        file_path = _uploads_dir / filename
        
        # Save file bytes
        content = await file.read()
        file_path.write_bytes(content)
        
        # Verify parser
        import pandas as pd
        df = pd.read_csv(file_path)
        tickers = []
        if not df.empty:
            cols_lower = [str(c).strip().lower() for c in df.columns]
            ticker_col = None
            for idx, col in enumerate(cols_lower):
                if col in ("ticker", "symbol", "stock", "code", "shares symbol", "instrument"):
                    ticker_col = df.columns[idx]
                    break
            if not ticker_col:
                for idx, col in enumerate(cols_lower):
                    if "ticker" in col or "symbol" in col or "stock" in col:
                        ticker_col = df.columns[idx]
                        break
            if not ticker_col:
                ticker_col = df.columns[0]
            tickers = [str(t).strip().upper() for t in df[ticker_col].dropna().unique() if str(t).strip() and str(t).strip().upper() not in ("TICKER", "SYMBOL", "STOCK", "NAN", "")]
            
        return {
            "status": "success",
            "filename": file.filename,
            "saved_path": f"uploads/{filename}",
            "tickers_detected": tickers[:8],
            "total_rows": len(df) if not df.empty else 0
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to save and parse CSV file: {str(e)}"})


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    # Create a new session for this connection
    session = session_manager.new_session()
    await ws.send_json({
        "type": "session",
        "session_id": session.session_id,
        "history_count": 0,
    })

    try:
        agent = await _get_agent()
    except Exception as e:
        await ws.send_json({"type": "error", "message": f"Agent init failed: {e}"})
        await ws.close()
        return

    try:
        while True:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                break

            # ── New-session request ──────────────────────────────────────────
            if data.get("type") == "new_session":
                session = session_manager.reset(session.session_id)
                await ws.send_json({
                    "type": "session",
                    "session_id": session.session_id,
                    "history_count": 0,
                })
                continue

            # ── Regular query ────────────────────────────────────────────────
            query = str(data.get("query", "")).strip()
            if not query:
                continue

            await ws.send_json({"type": "thinking"})

            # Build message list: history + new human message
            history = session_manager.get_messages(session.session_id)
            messages = history + [("human", query)]

            callback = WebSocketCallbackHandler(ws)
            t_start = time.time()

            try:
                result = await agent.ainvoke(
                    {"messages": messages},
                    config={"callbacks": [callback], "recursion_limit": 100},
                )

                response_text = _extract_response(result)
                elapsed = round(time.time() - t_start, 2)

                # Persist exchange to session history
                session_manager.add_exchange(session.session_id, query, response_text)
                history_count = len(session_manager.get_messages(session.session_id)) // 2

                # Print token summary to server console
                from agent import _print_token_summary
                _print_token_summary(callback.accumulator, label="Web Request")

                tokens_data = {
                    "input": callback.accumulator.input_tokens,
                    "output": callback.accumulator.output_tokens,
                    "cache_read": callback.accumulator.cache_read_tokens,
                    "cache_creation": callback.accumulator.cache_creation_tokens,
                    "total": callback.accumulator.total_tokens
                }

                await ws.send_json({"type": "response", "content": response_text})
                await ws.send_json({
                    "type": "done",
                    "elapsed": elapsed,
                    "history_count": history_count,
                    "tokens": tokens_data,
                })

            except Exception as e:
                elapsed = round(time.time() - t_start, 2)
                from agent import _print_token_summary
                _print_token_summary(callback.accumulator, label="Web Request (Failed)")
                tokens_data = {
                    "input": callback.accumulator.input_tokens,
                    "output": callback.accumulator.output_tokens,
                    "cache_read": callback.accumulator.cache_read_tokens,
                    "cache_creation": callback.accumulator.cache_creation_tokens,
                    "total": callback.accumulator.total_tokens
                }
                await ws.send_json({"type": "error", "message": str(e)})
                await ws.send_json({
                    "type": "done",
                    "elapsed": elapsed,
                    "history_count": 0,
                    "tokens": tokens_data,
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


def _extract_response(result) -> str:
    """Pull the final assistant message text out of the agent result.

    Handles multiple content formats:
    - Plain string: returned as-is
    - Anthropic content blocks: [{"type": "text", "text": "..."}, ...]
    - OpenAI message object with .content attribute
    - LangChain AIMessage with .content
    """
    def _unwrap_content(content) -> str:
        """Recursively unwrap content to plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Anthropic / OpenAI content blocks: [{"type": "text", "text": "..."}, ...]
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(block.get("text", ""))
                    elif "text" in block:
                        parts.append(str(block["text"]))
                    # skip tool_use, image, etc.
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p).strip()
        if isinstance(content, dict):
            # Single block
            if content.get("type") == "text":
                return content.get("text", "")
            if "text" in content:
                return str(content["text"])
        return str(content)

    if isinstance(result, dict):
        msgs = result.get("messages", [])
        if msgs:
            last = msgs[-1]
            if hasattr(last, "content"):
                return _unwrap_content(last.content)
            if isinstance(last, dict):
                return _unwrap_content(last.get("content", last))
            return str(last)
        if "output" in result:
            return _unwrap_content(result["output"])
        return json.dumps(result, ensure_ascii=False, default=str)

    return _unwrap_content(result)



# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    print("╔════════════════════════════════════════════╗")
    print("║   📈 Stock Analysis Deep Agent — Web UI    ║")
    print("╠════════════════════════════════════════════╣")
    print("║   http://localhost:8000                    ║")
    print("╚════════════════════════════════════════════╝")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
