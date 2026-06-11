"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              Stock Analysis Deep Agent – RAG Tools                          ║
║                                                                              ║
║  Provides two retrieval-augmented generation (RAG) tools backed by a        ║
║  FAISS vector store loaded from the knowledge_base/ directory.              ║
║                                                                              ║
║  Tools:                                                                      ║
║    search_investment_knowledge – investment frameworks & methodologies       ║
║    search_market_history       – historical market events & crises           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_BASE_DIR   = Path(__file__).parent
_KB_DIR     = _BASE_DIR / "knowledge_base"
_VS_DIR     = _BASE_DIR / "vector_store"

_FRAMEWORK_DIR  = _KB_DIR / "investment_frameworks"
_HISTORY_DIR    = _KB_DIR / "market_history"
_VS_FRAMEWORK   = _VS_DIR / "investment_frameworks"
_VS_HISTORY     = _VS_DIR / "market_history"


# ─────────────────────────────────────────────────────────────────────────────
# Vector Store Loader (lazy, cached)
# ─────────────────────────────────────────────────────────────────────────────

_vs_cache: dict = {}


def _load_or_build_vectorstore(docs_dir: Path, vs_path: Path):
    """Load an existing FAISS index or build one from markdown files."""
    cache_key = str(vs_path)
    if cache_key in _vs_cache:
        return _vs_cache[cache_key]

    try:
        from langchain_openai import OpenAIEmbeddings
        from langchain_community.vectorstores import FAISS
        from langchain_community.document_loaders import DirectoryLoader, TextLoader
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ImportError as e:
        logger.warning(f"RAG dependencies not installed: {e}. RAG tools will be disabled.")
        return None

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    # Load from existing index if available
    if vs_path.exists():
        try:
            vs = FAISS.load_local(
                str(vs_path),
                embeddings,
                allow_dangerous_deserialization=True,
            )
            logger.info(f"Loaded existing FAISS index from {vs_path}")
            _vs_cache[cache_key] = vs
            return vs
        except Exception as e:
            logger.warning(f"Could not load existing index ({e}), rebuilding…")

    # Build from markdown files
    if not docs_dir.exists() or not any(docs_dir.glob("*.md")):
        logger.warning(f"No markdown files found in {docs_dir}. RAG tool will return empty results.")
        return None

    try:
        loader = DirectoryLoader(
            str(docs_dir),
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
            show_progress=False,
        )
        documents = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=120,
            separators=["\n## ", "\n### ", "\n\n", "\n", " "],
        )
        chunks = splitter.split_documents(documents)

        logger.info(f"Building FAISS index from {len(chunks)} chunks in {docs_dir}…")
        vs = FAISS.from_documents(chunks, embeddings)

        vs_path.mkdir(parents=True, exist_ok=True)
        vs.save_local(str(vs_path))
        logger.info(f"FAISS index saved to {vs_path}")

        _vs_cache[cache_key] = vs
        return vs

    except Exception as e:
        logger.error(f"Failed to build FAISS index: {e}")
        return None


def _query_vectorstore(vs, query: str, k: int = 4) -> str:
    """Run a similarity search and return formatted text chunks."""
    if vs is None:
        return json.dumps({
            "error": "Knowledge base not available. Check RAG dependencies and knowledge_base/ directory.",
            "query": query,
        })
    try:
        docs = vs.similarity_search(query, k=k)
        if not docs:
            return json.dumps({"query": query, "results": [], "message": "No relevant documents found."})

        results = []
        for i, doc in enumerate(docs, 1):
            source = Path(doc.metadata.get("source", "unknown")).name
            results.append({
                "rank": i,
                "source": source,
                "content": doc.page_content.strip(),
            })

        return json.dumps({
            "query": query,
            "num_results": len(results),
            "results": results,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "query": query})


# ─────────────────────────────────────────────────────────────────────────────
# RAG Tool 1 – Investment Knowledge
# ─────────────────────────────────────────────────────────────────────────────

@tool
def search_investment_knowledge(query: str) -> str:
    """
    Search the investment methodology knowledge base for frameworks, strategies,
    and analytical approaches.

    Use this tool when you need to answer questions about:
    - Value investing principles (Graham, Buffett, DCF, margin of safety)
    - Growth investing strategies (PEG ratio, GARP, Rule of 40, TAM analysis)
    - Technical analysis methodology (trend identification, indicator interpretation)
    - Portfolio theory (Sharpe ratio, diversification, risk parity, rebalancing)
    - Any question about HOW to analyze or evaluate stocks/portfolios

    Args:
        query: Natural language question about investment methods or frameworks.
               Examples: "How to calculate intrinsic value using DCF?",
                         "What is a good PEG ratio for growth stocks?",
                         "How to interpret MACD divergence?"

    Returns:
        JSON with ranked relevant passages from the knowledge base.
    """
    vs = _load_or_build_vectorstore(_FRAMEWORK_DIR, _VS_FRAMEWORK)
    return _query_vectorstore(vs, query)


# ─────────────────────────────────────────────────────────────────────────────
# RAG Tool 2 – Market History
# ─────────────────────────────────────────────────────────────────────────────

@tool
def search_market_history(query: str) -> str:
    """
    Search the historical market events knowledge base for context on past
    crises, bull/bear markets, and significant financial events.

    Use this tool when you need to answer questions about:
    - The 2000 dot-com bubble (NASDAQ crash, valuation excesses, survivors)
    - The 2008 financial crisis (subprime, Lehman, government bailouts)
    - The 2020 COVID crash and recovery (fastest bear market, FAANGM surge)
    - The 2022 bear market (inflation, Fed rate hikes, growth stock collapse)
    - Lessons from past market cycles and how they apply to current conditions
    - Historical analogies for current market situations

    Args:
        query: Natural language question about historical market events.
               Examples: "What caused the 2008 financial crisis?",
                         "How did stocks recover after COVID crash?",
                         "What happened to tech stocks in 2022?"

    Returns:
        JSON with ranked relevant passages from the market history knowledge base.
    """
    vs = _load_or_build_vectorstore(_HISTORY_DIR, _VS_HISTORY)
    return _query_vectorstore(vs, query)


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

RAG_TOOLS = [search_investment_knowledge, search_market_history]


def preload_vectorstores():
    """Pre-build or load FAISS indexes at startup (call once in agent.py)."""
    from rich.console import Console
    console = Console()

    for name, docs_dir, vs_path in [
        ("Investment Knowledge", _FRAMEWORK_DIR, _VS_FRAMEWORK),
        ("Market History",       _HISTORY_DIR,   _VS_HISTORY),
    ]:
        try:
            vs = _load_or_build_vectorstore(docs_dir, vs_path)
            if vs:
                console.print(f"[green]✓ RAG ready: {name}[/green]")
            else:
                console.print(f"[yellow]⚠ RAG unavailable: {name} (missing docs or deps)[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ RAG error ({name}): {e}[/red]")
