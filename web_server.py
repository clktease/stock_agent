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
import asyncio
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, List, Optional, Set, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import AsyncCallbackHandler
from langgraph.errors import GraphInterrupt

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    print("⚠ apscheduler not installed. Run: pip install apscheduler")

from influencer_tracking import (
    _load_influencers, _add_influencer, _remove_influencer, _set_influencer_enabled,
    _update_influencer_check_state,
    save_influencer_alert, load_influencer_alerts,
    _search_influencer_mentions, compute_url_set_hash,
    build_influencer_alert_prompt, infer_investment_relevance,
)

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


# ─────────────────────────────────────────────────────────────────────────────
# SSE Broadcaster (fan-out scheduled results to all connected clients)
# ─────────────────────────────────────────────────────────────────────────────

class SSEBroadcaster:
    """Manages a set of SSE queues – one per connected /events client."""

    def __init__(self):
        self._queues: Set[asyncio.Queue] = set()

    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    async def broadcast(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str)
        dead = set()
        for q in list(self._queues):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.add(q)
        for q in dead:
            self._queues.discard(q)


sse_broadcaster = SSEBroadcaster()


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled Results Storage
# ─────────────────────────────────────────────────────────────────────────────

_results_dir = Path(__file__).parent / "scheduled_results"
_results_dir.mkdir(exist_ok=True)
_RESULTS_KEEP = 30  # keep last N results per job


def save_scheduled_result(job_id: str, prompt: str, result_text: str) -> dict:
    """Persist a scheduled job result to disk."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "job_id": job_id,
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
        "prompt": prompt,
        "result": result_text,
    }
    path = _results_dir / f"{job_id}_{ts}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # Prune old results for this job
    old_files = sorted(_results_dir.glob(f"{job_id}_*.json"), key=lambda p: p.name)
    for f in old_files[:-_RESULTS_KEEP]:
        try:
            f.unlink()
        except OSError:
            pass
    return record


def load_scheduled_results(job_id: str, limit: int = 10) -> list:
    """Load the most recent results for a job."""
    files = sorted(_results_dir.glob(f"{job_id}_*.json"), key=lambda p: p.name, reverse=True)
    results = []
    for f in files[:limit]:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Jobs Persistence (jobs.json)
# ─────────────────────────────────────────────────────────────────────────────

_jobs_file = Path(__file__).parent / "jobs.json"


def _load_jobs() -> list:
    if _jobs_file.exists():
        try:
            data = json.loads(_jobs_file.read_text(encoding="utf-8"))
            return data.get("jobs", [])
        except Exception:
            pass
    return []


def _save_jobs(jobs: list) -> None:
    _jobs_file.write_text(
        json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Natural Language Schedule Parser
# ─────────────────────────────────────────────────────────────────────────────

# Map Chinese/English time words to (hour, minute)
_TIME_MAP = [
    (r"凌晨(\d+)點半?",   lambda m: (int(m.group(1)), 30 if "半" in m.group(0) else 0)),
    (r"早上(\d+)點半?",   lambda m: (int(m.group(1)), 30 if "半" in m.group(0) else 0)),
    (r"上午(\d+)點半?",   lambda m: (int(m.group(1)), 30 if "半" in m.group(0) else 0)),
    (r"中午(\d+)點半?",   lambda m: (int(m.group(1)), 30 if "半" in m.group(0) else 0)),
    (r"下午(\d+)點半?",   lambda m: (int(m.group(1)) + 12, 30 if "半" in m.group(0) else 0)),
    (r"晚上(\d+)點半?",   lambda m: (int(m.group(1)) + (12 if int(m.group(1)) < 12 else 0),
                                      30 if "半" in m.group(0) else 0)),
    (r"午夜(\d+)點半?",   lambda m: (int(m.group(1)), 30 if "半" in m.group(0) else 0)),
    # digit only: 21:00 / 9pm
    (r"(\d{1,2}):(\d{2})\s*(?:am|pm)?", lambda m: (
        int(m.group(1)) + (12 if "pm" in m.group(0).lower() and int(m.group(1)) != 12 else 0),
        int(m.group(2)),
    )),
    (r"(\d{1,2})\s*pm",  lambda m: (int(m.group(1)) + (12 if int(m.group(1)) != 12 else 0), 0)),
    (r"(\d{1,2})\s*am",  lambda m: (int(m.group(1)) % 12, 0)),
]

_WEEKDAY_MAP = {
    "星期一": 1, "週一": 1, "Monday": 1, "monday": 1, "mon": 1,
    "星期二": 2, "週二": 2, "Tuesday": 2, "tuesday": 2, "tue": 2,
    "星期三": 3, "週三": 3, "Wednesday": 3, "wednesday": 3, "wed": 3,
    "星期四": 4, "週四": 4, "Thursday": 4, "thursday": 4, "thu": 4,
    "星期五": 5, "週五": 5, "Friday": 5, "friday": 5, "fri": 5,
    "星期六": 6, "週六": 6, "Saturday": 6, "saturday": 6, "sat": 6,
    "星期日": 7, "週日": 7, "Sunday": 7, "sunday": 7, "sun": 7,
    "星期天": 7, "週天": 7,
}

_SCHEDULE_KEYWORDS = [
    "每天", "每日", "每週", "每周", "每個星期", "每星期",
    "every day", "everyday", "daily", "every week", "weekly",
    "定時", "排程", "自動", "schedule",
]


def parse_schedule_intent(text: str) -> Optional[dict]:
    """
    Detect and parse a scheduling intent from natural language.

    Returns a dict with keys: cron, description, prompt_for_agent
    or None if no scheduling intent is detected.
    """
    text_lower = text.lower()

    # Must contain a scheduling keyword
    if not any(kw in text for kw in _SCHEDULE_KEYWORDS):
        # fallback English check
        if not any(kw in text_lower for kw in ["every day", "everyday", "daily", "every week", "weekly", "schedule"]):
            return None

    # Parse time
    hour, minute = 9, 0  # default: 09:00
    for pattern, extractor in _TIME_MAP:
        m = re.search(pattern, text)
        if m:
            try:
                hour, minute = extractor(m)
                hour = max(0, min(23, hour))
                minute = max(0, min(59, minute))
            except Exception:
                pass
            break

    # Parse weekday (for weekly schedules)
    day_of_week = "*"
    for word, dow in _WEEKDAY_MAP.items():
        if word in text:
            day_of_week = str(dow)
            break

    # Determine frequency label
    is_weekly = any(kw in text for kw in ["每週", "每周", "每個星期", "every week", "weekly"]) \
                or day_of_week != "*"

    # Build cron expression
    cron = f"{minute} {hour} * * {day_of_week}"

    # Human-readable description
    dow_names = {
        "1": "週一", "2": "週二", "3": "週三", "4": "週四",
        "5": "週五", "6": "週六", "7": "週日", "*": "每天",
    }
    freq_label = dow_names.get(day_of_week, "每天") if is_weekly else "每天"
    time_label = f"{hour:02d}:{minute:02d}"
    description = f"{freq_label} {time_label} 自動執行"

    # The actual prompt sent to the agent (strip schedule-related words)
    # We keep the core analytical intent
    clean = re.sub(
        r"(每天|每日|每週|每周|每個星期|每星期|定時|排程|自動|幫我|help me|every\s+day|everyday|daily|every\s+week|weekly|schedule[d]?\s*(to)?)",
        "", text, flags=re.IGNORECASE,
    )
    # Remove time expressions
    for pattern, _ in _TIME_MAP:
        clean = re.sub(pattern, "", clean)
    for word in _WEEKDAY_MAP:
        clean = clean.replace(word, "")
    # Remove time-of-day words
    for tw in ["晚上", "早上", "上午", "下午", "凌晨", "中午", "午夜",
               "morning", "evening", "night", "afternoon", "midnight", "noon",
               "點半", "點", "pm", "am"]:
        clean = clean.replace(tw, "")
    clean = re.sub(r"\s+", " ", clean).strip(" 。，、！!.,")
    if not clean:
        clean = "請進行美股整體市場分析，包含大盤指數（SPY、QQQ、DIA）、VIX 恐慌指數、以及熱門科技股表現摘要。"

    return {
        "cron": cron,
        "description": description,
        "hour": hour,
        "minute": minute,
        "day_of_week": day_of_week,
        "prompt_for_agent": clean,
        "original_text": text,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Manager
# ─────────────────────────────────────────────────────────────────────────────

class SchedulerManager:
    """Wraps APScheduler and manages cron-based agent jobs."""

    def __init__(self):
        if HAS_APSCHEDULER:
            self.scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
        else:
            self.scheduler = None
        self._jobs: list = []   # list of job dicts (mirrors jobs.json)

    def start(self) -> None:
        if not self.scheduler:
            return
        self._jobs = _load_jobs()
        for job in self._jobs:
            if job.get("enabled", True):
                self._register_apscheduler_job(job)
        self.scheduler.start()
        print(f"✓ Scheduler started with {len(self._jobs)} job(s)")

    def stop(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _register_apscheduler_job(self, job: dict) -> None:
        if not self.scheduler:
            return
        try:
            cron_parts = job["cron"].split()
            trigger = CronTrigger(
                minute=cron_parts[0],
                hour=cron_parts[1],
                day=cron_parts[2],
                month=cron_parts[3],
                day_of_week=cron_parts[4],
                timezone="Asia/Taipei",
            )
            self.scheduler.add_job(
                execute_scheduled_job,
                trigger=trigger,
                args=[job["id"], job["prompt"]],
                id=job["id"],
                replace_existing=True,
            )
        except Exception as e:
            print(f"⚠ Failed to register job {job.get('id')}: {e}")

    def add_job(self, cron: str, prompt: str, description: str) -> dict:
        job = {
            "id": str(uuid.uuid4()),
            "cron": cron,
            "prompt": prompt,
            "description": description,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "last_run": None,
            "enabled": True,
        }
        self._jobs.append(job)
        _save_jobs(self._jobs)
        if job["enabled"]:
            self._register_apscheduler_job(job)
        return job

    def list_jobs(self) -> list:
        return list(self._jobs)

    def get_job(self, job_id: str) -> Optional[dict]:
        return next((j for j in self._jobs if j["id"] == job_id), None)

    def delete_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        self._jobs = [j for j in self._jobs if j["id"] != job_id]
        _save_jobs(self._jobs)
        if self.scheduler:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
        return True

    def set_enabled(self, job_id: str, enabled: bool) -> Optional[dict]:
        job = self.get_job(job_id)
        if not job:
            return None
        job["enabled"] = enabled
        _save_jobs(self._jobs)
        if self.scheduler:
            if enabled:
                self._register_apscheduler_job(job)
            else:
                try:
                    self.scheduler.remove_job(job_id)
                except Exception:
                    pass
        return job

    def update_last_run(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job:
            job["last_run"] = datetime.now(tz=timezone.utc).isoformat()
            _save_jobs(self._jobs)


scheduler_manager = SchedulerManager()


async def execute_scheduled_job(job_id: str, prompt: str) -> None:
    """Called by APScheduler. Runs the agent and broadcasts results via SSE."""
    print(f"⏰ Executing scheduled job {job_id}: {prompt[:60]}...")
    try:
        agent = await _get_agent()
    except Exception as e:
        await sse_broadcaster.broadcast({
            "type": "scheduled_error",
            "job_id": job_id,
            "message": f"Agent init failed: {e}",
        })
        return

    scheduler_manager.update_last_run(job_id)
    job = scheduler_manager.get_job(job_id)
    desc = job["description"] if job else "定時分析"

    # Signal start
    await sse_broadcaster.broadcast({
        "type": "scheduled_start",
        "job_id": job_id,
        "description": desc,
        "prompt": prompt,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
    })

    try:
        session = session_manager.new_session()
        config = {
            "configurable": {"thread_id": f"scheduled_{job_id}_{time.time()}"},
            "recursion_limit": 100,
        }
        result = await agent.ainvoke(
            {"messages": [("human", prompt)]},
            config=config,
        )
        response_text = _extract_response(result)
        session_manager.add_exchange(session.session_id, prompt, response_text)

        record = save_scheduled_result(job_id, prompt, response_text)

        await sse_broadcaster.broadcast({
            "type": "scheduled_result",
            "job_id": job_id,
            "description": desc,
            "session_id": session.session_id,
            "result": response_text,
            "executed_at": record["executed_at"],
        })
        print(f"✓ Scheduled job {job_id} completed.")
    except Exception as e:
        await sse_broadcaster.broadcast({
            "type": "scheduled_error",
            "job_id": job_id,
            "description": desc,
            "message": str(e),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Influencer Tracking — background poll cycle
# ─────────────────────────────────────────────────────────────────────────────

async def _run_influencer_check(influencer: dict, force: bool = False) -> Optional[dict]:
    """
    Check one tracked influencer for genuinely new coverage since the last poll.
    If new content is found (or `force=True`), synthesizes an investment-relevance
    analysis via the orchestrator agent (same pattern as execute_scheduled_job),
    persists the alert, and broadcasts it over SSE.

    Returns the saved alert record, or None if no alert was generated.
    """
    name = influencer["name"]
    influencer_id = influencer["id"]

    results = await asyncio.get_event_loop().run_in_executor(
        None, _search_influencer_mentions, name,
        influencer.get("aliases"), influencer.get("context_tickers"),
    )

    urls = [r["url"] for r in results]
    new_hash = compute_url_set_hash(urls)
    prev_urls = set(influencer.get("last_seen_urls") or [])
    prev_hash = influencer.get("last_seen_hash")

    new_items = [r for r in results if r["url"] not in prev_urls]
    is_first_check = prev_hash is None
    has_new_content = bool(new_items) and new_hash != prev_hash

    # Always advance the check-state, regardless of whether an alert fires.
    _update_influencer_check_state(influencer_id, urls, new_hash)

    if not force:
        if is_first_check:
            print(f"📋 Influencer baseline established for {name} ({len(results)} items) — no alert.")
            return None
        if not has_new_content:
            return None
    elif not new_items:
        # Forced check with nothing "new" — fall back to current results so the
        # user gets an immediate answer instead of a no-op.
        new_items = results

    if not new_items:
        return None

    context_tickers = influencer.get("context_tickers") or []
    prompt = build_influencer_alert_prompt(name, new_items, context_tickers)

    try:
        agent = await _get_agent()
    except Exception as e:
        await sse_broadcaster.broadcast({
            "type": "celebrity_alert_error", "influencer_id": influencer_id,
            "name": name, "message": f"Agent init failed: {e}",
        })
        return None

    await sse_broadcaster.broadcast({
        "type": "celebrity_check_start",
        "influencer_id": influencer_id,
        "name": name,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
    })

    try:
        session = session_manager.new_session()
        config = {
            "configurable": {"thread_id": f"influencer_{influencer_id}_{time.time()}"},
            "recursion_limit": 100,
        }
        result = await agent.ainvoke({"messages": [("human", prompt)]}, config=config)
        response_text = _extract_response(result)
        session_manager.add_exchange(session.session_id, prompt, response_text)

        has_relevance = infer_investment_relevance(response_text)
        source_urls = [item["url"] for item in new_items]
        record = save_influencer_alert(
            influencer_id, name, prompt, source_urls, has_relevance, response_text,
        )

        await sse_broadcaster.broadcast({
            "type": "celebrity_alert",
            "influencer_id": influencer_id,
            "name": name,
            "has_investment_relevance": has_relevance,
            "summary_snippet": response_text[:200],
            "result": response_text,
            "source_urls": source_urls,
            "executed_at": record["executed_at"],
        })
        print(f"✓ Influencer alert generated for {name}.")
        return record
    except Exception as e:
        await sse_broadcaster.broadcast({
            "type": "celebrity_alert_error", "influencer_id": influencer_id,
            "name": name, "message": str(e),
        })
        return None


async def run_influencer_poll_cycle() -> None:
    """Called by APScheduler on a fixed interval (celebrity_monitor_cycle).
    Sequentially checks all enabled tracked influencers for new content —
    sequential (not gather) to avoid bursting Tavily and to bound LLM cost."""
    influencers = _load_influencers()
    enabled = [i for i in influencers if i.get("enabled", True)]
    if not enabled:
        return
    print(f"👀 Influencer poll cycle: checking {len(enabled)} tracked figure(s)...")
    for influencer in enabled:
        try:
            await _run_influencer_check(influencer)
        except Exception as e:
            print(f"⚠ Influencer check failed for {influencer.get('name')}: {e}")
        await asyncio.sleep(2)


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

    # Start cron scheduler
    scheduler_manager.start()

    # Register the system-level influencer monitoring cycle (distinct from
    # user-authored jobs.json cron jobs — config-driven via env var, not
    # editable through /schedule*).
    if scheduler_manager.scheduler:
        poll_minutes = int(os.environ.get("INFLUENCER_POLL_INTERVAL_MINUTES", "30"))
        scheduler_manager.scheduler.add_job(
            run_influencer_poll_cycle,
            trigger=IntervalTrigger(minutes=poll_minutes),
            id="celebrity_monitor_cycle",
            replace_existing=True,
            max_instances=1,
        )
        print(f"✓ Influencer monitor cycle registered (every {poll_minutes} min)")

    yield

    # Shutdown
    scheduler_manager.stop()


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
    return {"status": "ok", "agent_ready": _agent is not None, "scheduler_running": bool(scheduler_manager.scheduler and scheduler_manager.scheduler.running)}


# ─────────────────────────────────────────────────────────────────────────────
# SSE – Scheduled Result Push
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/events")
async def sse_endpoint(request: Request):
    """Server-Sent Events stream for scheduled job notifications."""
    q = sse_broadcaster.register()

    async def event_stream() -> AsyncGenerator[str, None]:
        # Send heartbeat first
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield "data: {\"type\":\"ping\"}\n\n"
        finally:
            sse_broadcaster.unregister(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Schedule REST APIs
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/schedule/detect")
async def detect_schedule(data: dict):
    """Detect if a message contains a scheduling intent. Returns parsed intent or null."""
    text = str(data.get("text", "")).strip()
    if not text:
        return {"intent": None}
    intent = parse_schedule_intent(text)
    return {"intent": intent}


@app.post("/schedule")
async def create_schedule(data: dict):
    """Create a new scheduled job."""
    cron    = str(data.get("cron", "")).strip()
    prompt  = str(data.get("prompt", "")).strip()
    description = str(data.get("description", "定時分析")).strip()

    if not cron or not prompt:
        return JSONResponse(status_code=400, content={"error": "cron and prompt are required"})

    # Basic cron validation (5 fields)
    if len(cron.split()) != 5:
        return JSONResponse(status_code=400, content={"error": "Invalid cron expression (need 5 fields)"})

    job = scheduler_manager.add_job(cron=cron, prompt=prompt, description=description)
    return {"status": "created", "job": job}


@app.get("/schedule")
async def list_schedules():
    """List all scheduled jobs."""
    jobs = scheduler_manager.list_jobs()
    return {"jobs": jobs}


@app.delete("/schedule/{job_id}")
async def delete_schedule(job_id: str):
    """Delete a scheduled job."""
    ok = scheduler_manager.delete_job(job_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return {"status": "deleted", "job_id": job_id}


@app.patch("/schedule/{job_id}")
async def update_schedule(job_id: str, data: dict):
    """Pause or resume a scheduled job."""
    enabled = data.get("enabled")
    if enabled is None:
        return JSONResponse(status_code=400, content={"error": "enabled field required"})
    job = scheduler_manager.set_enabled(job_id, bool(enabled))
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return {"status": "updated", "job": job}


@app.get("/schedule/{job_id}/results")
async def get_schedule_results(job_id: str, limit: int = 10):
    """Get execution history for a scheduled job."""
    results = load_scheduled_results(job_id, limit=limit)
    return {"job_id": job_id, "results": results}


# ─────────────────────────────────────────────────────────────────────────────
# Influencer Tracking REST APIs
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/influencers")
async def create_influencer(data: dict):
    """Add (or update) a public figure to the background-monitoring watchlist."""
    name = str(data.get("name", "")).strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "name is required"})
    aliases = data.get("aliases") or []
    context_tickers = data.get("context_tickers") or []
    entry = _add_influencer(name, aliases, context_tickers)
    return {"status": "created", "influencer": entry}


@app.get("/influencers")
async def list_influencers():
    """List everyone currently tracked."""
    return {"influencers": _load_influencers()}


@app.delete("/influencers/{influencer_id}")
async def delete_influencer(influencer_id: str):
    """Stop tracking a public figure."""
    ok = _remove_influencer(influencer_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Influencer not found"})
    return {"status": "deleted", "influencer_id": influencer_id}


@app.patch("/influencers/{influencer_id}")
async def update_influencer(influencer_id: str, data: dict):
    """Pause or resume background monitoring for a tracked influencer."""
    enabled = data.get("enabled")
    if enabled is None:
        return JSONResponse(status_code=400, content={"error": "enabled field required"})
    entry = _set_influencer_enabled(influencer_id, bool(enabled))
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Influencer not found"})
    return {"status": "updated", "influencer": entry}


@app.get("/influencers/{influencer_id}/alerts")
async def get_influencer_alerts(influencer_id: str, limit: int = 10):
    """Get alert history for a tracked influencer."""
    alerts = load_influencer_alerts(influencer_id, limit=limit)
    return {"influencer_id": influencer_id, "alerts": alerts}


@app.post("/influencers/{influencer_id}/check-now")
async def check_influencer_now(influencer_id: str, data: dict):
    """
    Manually trigger an immediate check for a tracked influencer, instead of
    waiting for the next background poll cycle. `force` (default true) skips
    the "no new content" dedup gate so the caller gets an immediate result.
    """
    influencers = _load_influencers()
    target = next((i for i in influencers if i["id"] == influencer_id), None)
    if not target:
        return JSONResponse(status_code=404, content={"error": "Influencer not found"})
    force = bool(data.get("force", True))
    record = await _run_influencer_check(target, force=force)
    if record is None:
        return {"status": "no_new_content", "influencer_id": influencer_id}
    return {"status": "alert_generated", "alert": record}


_uploads_dir = Path(__file__).parent / "uploads"
_uploads_dir.mkdir(exist_ok=True)
_holdings_history_dir = _uploads_dir / "history"
_holdings_history_dir.mkdir(exist_ok=True)
_holdings_index_file = _uploads_dir / "holdings_index.json"


# ─────────────────────────────────────────────────────────────────────────────
# Holdings History Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_holdings_index() -> list:
    """Load the list of saved holdings versions from disk."""
    if _holdings_index_file.exists():
        try:
            return json.loads(_holdings_index_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_holdings_index(index: list) -> None:
    _holdings_index_file.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _detect_ticker_col(df) -> str:
    """Find the ticker/symbol column in a holdings DataFrame."""
    cols_lower = [str(c).strip().lower() for c in df.columns]
    for idx, col in enumerate(cols_lower):
        if col in ("ticker", "symbol", "stock", "code", "shares symbol", "instrument", "代號", "股票代碼"):
            return df.columns[idx]
    for idx, col in enumerate(cols_lower):
        if "ticker" in col or "symbol" in col or "stock" in col or "代號" in col:
            return df.columns[idx]
    return df.columns[0]


def _detect_qty_col(df) -> Optional[str]:
    """Find the quantity/shares column in a holdings DataFrame."""
    cols_lower = [str(c).strip().lower() for c in df.columns]
    qty_keywords = ("qty", "quantity", "shares", "amount", "數量", "股數", "持股數", "單位")
    for idx, col in enumerate(cols_lower):
        if any(kw in col for kw in qty_keywords):
            return df.columns[idx]
    # Fallback: second numeric column if available
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if len(numeric_cols) >= 1:
        return numeric_cols[0]
    return None


def _parse_holdings_df(df) -> dict:
    """Return {ticker: qty} dict from a DataFrame. qty=None if no qty col."""
    ticker_col = _detect_ticker_col(df)
    qty_col    = _detect_qty_col(df)
    result = {}
    for _, row in df.iterrows():
        t = str(row[ticker_col]).strip().upper()
        if not t or t in ("TICKER", "SYMBOL", "STOCK", "NAN", ""):
            continue
        qty = None
        if qty_col:
            try:
                qty = float(row[qty_col])
            except (ValueError, TypeError):
                qty = None
        result[t] = qty
    return result


def _compare_holdings(old_map: dict, new_map: dict) -> dict:
    """
    Compare two {ticker: qty} dicts.
    Returns:
      added:   [{ticker, qty}]
      removed: [{ticker, qty}]
      changed: [{ticker, old_qty, new_qty, delta}]
      unchanged: [ticker]
    """
    old_set = set(old_map)
    new_set = set(new_map)

    added   = [{"ticker": t, "qty": new_map[t]} for t in sorted(new_set - old_set)]
    removed = [{"ticker": t, "qty": old_map[t]} for t in sorted(old_set - new_set)]
    changed = []
    unchanged = []
    for t in sorted(old_set & new_set):
        o, n = old_map[t], new_map[t]
        if o is not None and n is not None:
            delta = n - o
            if abs(delta) > 1e-9:
                changed.append({"ticker": t, "old_qty": o, "new_qty": n, "delta": delta})
            else:
                unchanged.append(t)
        else:
            unchanged.append(t)
    return {"added": added, "removed": removed, "changed": changed, "unchanged": unchanged}


def _holdings_have_changed(old_map: dict, new_map: dict) -> bool:
    diff = _compare_holdings(old_map, new_map)
    return bool(diff["added"] or diff["removed"] or diff["changed"])


def _next_version_path(date_str: str) -> Path:
    """Return the next available versioned path for today."""
    for n in range(1, 9999):
        p = _holdings_history_dir / f"holdings_{date_str}_{n:03d}.csv"
        if not p.exists():
            return p
    raise RuntimeError("Too many holdings versions for today")


def _save_holdings_version(content_bytes: bytes, new_map: dict, tickers: list, filename: str) -> dict:
    """
    Check whether holdings changed vs the latest saved version.
    If changed (or no history), save a new versioned file and update index.
    Returns a result dict with: is_new_version, diff, version_path, version_id.
    """
    import pandas as pd
    import io

    index = _load_holdings_index()
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")

    diff = None
    is_new_version = True

    if index:
        latest = index[-1]
        latest_path = Path(__file__).parent / latest["path"]
        if latest_path.exists():
            try:
                old_df = pd.read_csv(latest_path)
                old_map = _parse_holdings_df(old_df)
                diff = _compare_holdings(old_map, new_map)
                is_new_version = _holdings_have_changed(old_map, new_map)
            except Exception:
                is_new_version = True

    if is_new_version:
        version_path = _next_version_path(date_str)
        version_path.write_bytes(content_bytes)
        rel_path = f"uploads/history/{version_path.name}"
        version_id = version_path.stem

        entry = {
            "version_id": version_id,
            "path": rel_path,
            "filename": filename,
            "date": date_str,
            "saved_at": datetime.now(tz=timezone.utc).isoformat(),
            "tickers": tickers,
            "total_rows": len(new_map),
        }
        index.append(entry)
        _save_holdings_index(index)
    else:
        # Reuse the existing latest path
        latest = index[-1]
        rel_path = latest["path"]
        version_id = latest["version_id"]

    return {
        "is_new_version": is_new_version,
        "diff": diff,
        "version_path": rel_path,
        "version_id": version_id,
    }


@app.post("/upload")
async def upload_holdings(file: UploadFile = File(...), session_id: str = "default"):
    if not file.filename.endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Only CSV files are supported."})

    try:
        import pandas as pd
        import io

        content = await file.read()

        # Also keep the legacy session file for backward compat
        legacy_path = _uploads_dir / f"holdings_{session_id}.csv"
        legacy_path.write_bytes(content)

        # Parse
        df = pd.read_csv(io.BytesIO(content))
        tickers = []
        new_map = {}
        if not df.empty:
            new_map = _parse_holdings_df(df)
            tickers = list(new_map.keys())

        # Version management
        version_result = _save_holdings_version(content, new_map, tickers, file.filename)

        return {
            "status": "success",
            "filename": file.filename,
            "saved_path": version_result["version_path"],
            "legacy_path": f"uploads/holdings_{session_id}.csv",
            "tickers_detected": tickers[:8],
            "total_rows": len(df) if not df.empty else 0,
            "is_new_version": version_result["is_new_version"],
            "version_id": version_result["version_id"],
            "diff": version_result["diff"],
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to save and parse CSV file: {str(e)}"})


@app.get("/holdings/latest")
async def get_latest_holdings():
    """Return metadata for the most recently saved holdings version."""
    index = _load_holdings_index()
    if not index:
        return {"latest": None}
    latest = index[-1]
    return {"latest": latest}


@app.get("/holdings/history")
async def get_holdings_history():
    """Return all saved holdings versions (newest first)."""
    index = _load_holdings_index()
    return {"versions": list(reversed(index))}


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

            callback = WebSocketCallbackHandler(ws)
            t_start = time.time()

            config = {
                "configurable": {"thread_id": f"{session.session_id}_{session.created_at}"},
                "callbacks": [callback],
                "recursion_limit": 100
            }

            try:
                run_input = {"messages": [("human", query)]}
                while True:
                    interrupted = False
                    hitl_req = None
                    result = None
                    
                    try:
                        result = await agent.ainvoke(
                            run_input,
                            config=config,
                        )
                        if isinstance(result, dict) and result.get("__interrupt__"):
                            interrupted = True
                            hitl_req = result["__interrupt__"][0].value
                    except GraphInterrupt as e:
                        interrupted = True
                        state = await agent.aget_state(config)
                        tasks = state.tasks
                        if tasks and tasks[0].interrupts:
                            hitl_req = tasks[0].interrupts[0].value
                    
                    if interrupted and hitl_req:
                        action_request = next(
                            (req for req in hitl_req.get("action_requests", []) if req.get("name") == "ask_clarification"),
                            None
                        )
                        if action_request:
                            args = action_request.get("args", {})
                            question = args.get("question", "請確認：")
                            options = args.get("options", [])
                            
                            await ws.send_json({
                                "type": "clarify",
                                "question": question,
                                "options": options
                            })
                            
                            # Wait for frontend's resume response
                            while True:
                                try:
                                    msg_data = await ws.receive_json()
                                except WebSocketDisconnect:
                                    raise
                                
                                if msg_data.get("type") == "resume":
                                    choice = msg_data.get("choice")
                                    from langgraph.types import Command
                                    run_input = Command(resume={"decisions": [{"type": "respond", "message": choice}]})
                                    break
                                elif msg_data.get("type") == "new_session":
                                    session = session_manager.reset(session.session_id)
                                    await ws.send_json({
                                        "type": "session",
                                        "session_id": session.session_id,
                                        "history_count": 0,
                                    })
                                    raise Exception("Session reset during clarification.")
                            continue
                    
                    # If not interrupted, break the execution loop
                    break

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
