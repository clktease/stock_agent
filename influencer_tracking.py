"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         Stock Analysis Deep Agent – Influencer Social Sentiment Tracking      ║
║                                                                              ║
║  Lets users track public figures (executives, fund managers, politicians,   ║
║  influencers) whose social/media statements may move markets. Reuses        ║
║  Tavily web search (the same mechanism as the news-sentiment-analyst's      ║
║  search_news tool) to find recent coverage, and is shared by both an        ║
║  on-demand query tool and the background polling cycle in web_server.py.    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent
_INFLUENCERS_FILE = _BASE_DIR / "tracked_influencers.json"
_ALERTS_DIR = _BASE_DIR / "influencer_alerts"
_ALERTS_DIR.mkdir(exist_ok=True)
_ALERTS_KEEP = 50  # keep last N alerts per influencer


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist persistence (tracked_influencers.json)
# ─────────────────────────────────────────────────────────────────────────────

def _load_influencers() -> list:
    if _INFLUENCERS_FILE.exists():
        try:
            data = json.loads(_INFLUENCERS_FILE.read_text(encoding="utf-8"))
            return data.get("influencers", [])
        except Exception:
            pass
    return []


def _save_influencers(influencers: list) -> None:
    _INFLUENCERS_FILE.write_text(
        json.dumps({"influencers": influencers}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _find_influencer(influencers: list, name_or_id: str) -> Optional[dict]:
    key = name_or_id.strip().lower()
    for inf in influencers:
        if inf.get("id") == name_or_id:
            return inf
        if inf.get("name", "").strip().lower() == key:
            return inf
        if any(a.strip().lower() == key for a in inf.get("aliases", [])):
            return inf
    return None


def _add_influencer(name: str, aliases: Optional[list] = None,
                     context_tickers: Optional[list] = None) -> dict:
    """Add a person to the watchlist, or refresh aliases/tickers if already tracked."""
    name = name.strip()
    influencers = _load_influencers()
    existing = _find_influencer(influencers, name)

    if existing:
        if aliases:
            existing["aliases"] = sorted(set(existing.get("aliases", [])) | set(aliases))
        if context_tickers:
            existing["context_tickers"] = sorted(
                set(existing.get("context_tickers", [])) | {t.upper() for t in context_tickers}
            )
        existing["enabled"] = True
        _save_influencers(influencers)
        return existing

    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "aliases": sorted(set(aliases or []) | {name}),
        "context_tickers": sorted({t.upper() for t in (context_tickers or [])}),
        "enabled": True,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "last_checked_at": None,
        "last_seen_urls": [],
        "last_seen_hash": None,
        "alert_count": 0,
    }
    influencers.append(entry)
    _save_influencers(influencers)
    return entry


def _remove_influencer(name_or_id: str) -> bool:
    influencers = _load_influencers()
    target = _find_influencer(influencers, name_or_id)
    if not target:
        return False
    influencers = [i for i in influencers if i["id"] != target["id"]]
    _save_influencers(influencers)
    return True


def _set_influencer_enabled(influencer_id: str, enabled: bool) -> Optional[dict]:
    influencers = _load_influencers()
    target = next((i for i in influencers if i["id"] == influencer_id), None)
    if not target:
        return None
    target["enabled"] = enabled
    _save_influencers(influencers)
    return target


def _update_influencer_check_state(influencer_id: str, urls: list, url_hash: str) -> None:
    influencers = _load_influencers()
    target = next((i for i in influencers if i["id"] == influencer_id), None)
    if not target:
        return
    target["last_checked_at"] = datetime.now(tz=timezone.utc).isoformat()
    target["last_seen_urls"] = urls
    target["last_seen_hash"] = url_hash
    _save_influencers(influencers)


def _increment_alert_count(influencer_id: str) -> None:
    influencers = _load_influencers()
    target = next((i for i in influencers if i["id"] == influencer_id), None)
    if not target:
        return
    target["alert_count"] = target.get("alert_count", 0) + 1
    _save_influencers(influencers)


# ─────────────────────────────────────────────────────────────────────────────
# Alert history persistence (mirrors save_scheduled_result / load_scheduled_results
# in web_server.py, but kept here since it's part of the influencer data model)
# ─────────────────────────────────────────────────────────────────────────────

def save_influencer_alert(influencer_id: str, name: str, query_used: str,
                           source_urls: list, has_investment_relevance: bool,
                           response_text: str) -> dict:
    """Persist an alert record to disk and prune old ones for this influencer."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "influencer_id": influencer_id,
        "name": name,
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
        "query_used": query_used,
        "source_urls": source_urls,
        "has_investment_relevance": has_investment_relevance,
        "response_text": response_text,
    }
    path = _ALERTS_DIR / f"{influencer_id}_{ts}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    old_files = sorted(_ALERTS_DIR.glob(f"{influencer_id}_*.json"), key=lambda p: p.name)
    for f in old_files[:-_ALERTS_KEEP]:
        try:
            f.unlink()
        except OSError:
            pass

    _increment_alert_count(influencer_id)
    return record


def load_influencer_alerts(influencer_id: str, limit: int = 10) -> list:
    files = sorted(_ALERTS_DIR.glob(f"{influencer_id}_*.json"), key=lambda p: p.name, reverse=True)
    results = []
    for f in files[:limit]:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Tavily search helper (shared by the on-demand tool and the background poller)
# ─────────────────────────────────────────────────────────────────────────────

def _search_influencer_mentions(name: str, aliases: Optional[list] = None,
                                 context_tickers: Optional[list] = None,
                                 max_results: int = 8) -> list:
    """
    Search Tavily for recent coverage of statements/posts by `name`.

    Returns a de-duplicated list of {title, url, content, published_date, score}
    sorted by relevance score (best effort — fields depend on what Tavily
    returns). Empty list if TAVILY_API_KEY is unset or the search fails; this
    makes the whole influencer-tracking feature a safe no-op without Tavily.
    """
    if not os.environ.get("TAVILY_API_KEY"):
        logger.warning("TAVILY_API_KEY not set — influencer tracking search is disabled.")
        return []

    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
    except ImportError:
        logger.warning("tavily-python / langchain_community Tavily tool not installed.")
        return []

    queries = [f'"{name}" 最新發言 OR 推文 OR 貼文 latest statement OR tweet OR post']
    if context_tickers:
        queries.append(f'"{name}" {" ".join(context_tickers)} news')

    seen_urls = set()
    merged: list = []
    try:
        searcher = TavilySearchResults(max_results=max_results, name="_influencer_search")
    except Exception as e:
        logger.warning(f"Could not init Tavily search: {e}")
        return []

    for q in queries:
        try:
            raw = searcher.invoke({"query": q})
        except Exception as e:
            logger.warning(f"Tavily search failed for '{q}': {e}")
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append({
                "title": item.get("title", ""),
                "url": url,
                "content": (item.get("content") or "")[:500],
                "published_date": item.get("published_date"),
                "score": item.get("score"),
            })

    merged.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return merged[:max_results]


def compute_url_set_hash(urls: list) -> str:
    """Cheap fingerprint of a result set, used by the poller to detect churn."""
    return hashlib.sha256("|".join(sorted(urls)).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Investment-relevance alert prompt (fed into the orchestrator agent, same
# invocation pattern as execute_scheduled_job in web_server.py)
# ─────────────────────────────────────────────────────────────────────────────

INFLUENCER_ALERT_PROMPT_TEMPLATE = """{name} 是被追蹤的公眾人物/意見領袖。以下是網路搜尋到的最新相關報導/貼文摘要（自上次檢查後新出現的內容）：

{formatted_items}

請完成以下任務：
1. 摘要 {name} 實際說了什麼，依據上述報導區分「確認的直接引述」與「媒體解讀/轉述」。
2. 評估這是否與特定股票、產業或資產類別有明確的投資關聯性。
   - 如果沒有明確的投資關聯性，請直接說明「本次言論無明顯投資意涵」，不要勉強套用個股評等或建議。
3. 若有明確關聯性，才視需要委派 technical-analyst / fundamental-analyst / news-sentiment-analyst /
   portfolio-manager 進行更深入的分析，並提出：關聯標的、可能影響方向、信心程度（高/中/低）。
4. 一律附上風險提示：單一言論驅動的訊號可能是雜訊或市場過度反應（例如迷因股 meme-stock 動態、
   訊息尚未證實、或有心人士刻意炒作/操縱），不構成正式投資建議，僅供參考。
5. 已知關聯標的提示（僅供參考，不代表結論必然與其相關）：{context_tickers}

請以繁體中文回覆。
"""


def format_influencer_items(items: list) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. 標題：{item.get('title') or '(無標題)'}\n"
            f"   來源連結：{item.get('url', '')}\n"
            f"   發布時間：{item.get('published_date') or '未知'}\n"
            f"   摘要：{item.get('content', '')}"
        )
    return "\n\n".join(lines)


def build_influencer_alert_prompt(name: str, items: list, context_tickers: Optional[list] = None) -> str:
    return INFLUENCER_ALERT_PROMPT_TEMPLATE.format(
        name=name,
        formatted_items=format_influencer_items(items),
        context_tickers=", ".join(context_tickers) if context_tickers else "無",
    )


def infer_investment_relevance(response_text: str) -> bool:
    """Lightweight heuristic: does the synthesized response say there's no relevance?"""
    no_relevance_markers = ["無明顯投資意涵", "無投資關聯性", "沒有明顯的投資關聯", "無明確的投資關聯"]
    return not any(marker in response_text for marker in no_relevance_markers)


# ─────────────────────────────────────────────────────────────────────────────
# LLM-facing tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
def track_influencer(name: str, aliases: list[str] = None, context_tickers: list[str] = None) -> str:
    """
    Start tracking a public figure/celebrity/influencer's social media statements
    for potential investment relevance. Adds them to a persistent watchlist that
    is checked automatically in the background (roughly every 30 minutes by
    default); when genuinely new coverage of a statement is found, an investment-
    relevance analysis is generated and pushed to the user automatically.

    Use this when the user says things like "幫我追蹤馬斯克的言論" or
    "track what Cathie Wood says and alert me if it affects ARKK".

    Args:
        name: Full name of the person to track, e.g. "Elon Musk".
        aliases: Optional alternate names/handles, e.g. ["@elonmusk"].
        context_tickers: Optional tickers commonly associated with this person,
                         e.g. ["TSLA"], used to bias search relevance. Not required.

    Returns:
        JSON confirming the watchlist entry. Note: the FIRST check establishes a
        baseline and will not trigger an alert by itself — only genuinely new
        content found on subsequent checks triggers a notification.
    """
    entry = _add_influencer(name, aliases, context_tickers)
    return json.dumps({
        "status": "tracking",
        "influencer": entry,
        "note": "首次檢查只會建立基準資料，不會立即發出警示；之後偵測到新內容才會通知。",
    }, ensure_ascii=False, default=str)


@tool
def untrack_influencer(name: str) -> str:
    """
    Stop tracking a previously tracked public figure. Removes them from the
    background-monitoring watchlist entirely.

    Args:
        name: The name (or alias) as previously tracked.

    Returns:
        JSON status: {"status": "removed"} or {"status": "not_found"}.
    """
    removed = _remove_influencer(name)
    return json.dumps({"status": "removed" if removed else "not_found", "name": name}, ensure_ascii=False)


@tool
def list_tracked_influencers() -> str:
    """
    List everyone currently being tracked for investment-relevant social/media
    statements, including when they were last checked and how many alerts have
    fired for them.

    Returns:
        JSON with the full watchlist.
    """
    return json.dumps({"influencers": _load_influencers()}, ensure_ascii=False, default=str)


@tool
def get_recent_statements(name: str) -> str:
    """
    Search the web for recent statements/posts/coverage of ANY public figure
    (does not need to be on the tracked watchlist) — for one-off questions like
    "what has Elon Musk said about Tesla this week?". This tool returns raw
    search hits; distinguish confirmed direct quotes from media interpretation
    when summarizing them for the user.

    Args:
        name: The person's name to search for.

    Returns:
        JSON list of {title, url, content, published_date} search results,
        most relevant first. Empty list if no web-search capability is
        configured (TAVILY_API_KEY missing) or nothing was found.
    """
    influencers = _load_influencers()
    tracked = _find_influencer(influencers, name)
    aliases = tracked.get("aliases") if tracked else None
    tickers = tracked.get("context_tickers") if tracked else None
    results = _search_influencer_mentions(name, aliases, tickers)
    return json.dumps({"name": name, "results": results}, ensure_ascii=False, default=str)


INFLUENCER_TOOLS = [track_influencer, untrack_influencer, list_tracked_influencers, get_recent_statements]
