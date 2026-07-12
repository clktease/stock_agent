"""
╔══════════════════════════════════════════════════════════════════════════════╗
║      Stock Analysis Deep Agent - Market Timing & Advanced Strategy Tools     ║
║  Adapted from community "github_skills" (TraderMonty CSV data, IBD/O'Neil   ║
║  methodology, options/pair-trade math) to run on this project's existing    ║
║  yfinance + FRED data stack, with no new paid API dependency.               ║
╚══════════════════════════════════════════════════════════════════════════════╝

Design notes
------------
Several source skills overlapped heavily (market-breadth-analyzer /
uptrend-analyzer / breadth-chart-analyst / sector-analyst all read the same
TraderMonty CSVs; ibd-distribution-day-monitor / ftd-detector are two sides of
the same O'Neil distribution/follow-through-day mechanic; market-top-detector /
us-market-bubble-detector both produce a "how risky is the market right now"
score). Rather than port them 1:1, each cluster is consolidated into one tool
below. Composite scores are simplified, clearly-labeled adaptations of the
original multi-component weighted models -- not byte-for-byte ports -- so they
stay maintainable without an FMP/FINVIZ Elite subscription.
"""

import io
import itertools
import json
import math
import warnings
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from langchain_core.tools import tool

warnings.filterwarnings("ignore")

import logging
logging.getLogger("yfinance").disabled = True
logging.getLogger("yfinance").propagate = False


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value) -> Optional[float]:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_cdf(x: float) -> float:
    """Standard normal CDF without a scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _fetch_csv(url: str, timeout: int = 20) -> pd.DataFrame:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "deep-agent-market-tools/1.0"})
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def _pct(value: Optional[float]) -> Optional[float]:
    """Normalize a ratio that may be given as 0-1 or 0-100 into 0-100."""
    if value is None:
        return None
    return value * 100.0 if value <= 1.0 else value


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1 - Market Breadth (merges: market-breadth-analyzer, uptrend-analyzer,
#          breadth-chart-analyst [CSV mode], sector-analyst)
# ─────────────────────────────────────────────────────────────────────────────

BREADTH_CSV_URL = "https://tradermonty.github.io/market-breadth-analysis/market_breadth_data.csv"
UPTREND_CSV_URL = "https://raw.githubusercontent.com/tradermonty/uptrend-dashboard/main/data/uptrend_ratio_timeseries.csv"
SECTOR_CSV_URL = "https://raw.githubusercontent.com/tradermonty/uptrend-dashboard/main/data/sector_summary.csv"

_BREADTH_ZONES = [
    (80, "Strong", "90-100%"),
    (60, "Healthy", "75-90%"),
    (40, "Neutral", "60-75%"),
    (20, "Weakening", "40-60%"),
    (0, "Critical", "25-40%"),
]


def _classify_zone(score: float, zones: list) -> tuple:
    for threshold, label, exposure in zones:
        if score >= threshold:
            return label, exposure
    return zones[-1][1], zones[-1][2]


def _market_breadth_data() -> dict:
    """Raw data + composite score, reused internally by other tools."""
    breadth_df = _fetch_csv(BREADTH_CSV_URL)
    uptrend_df = _fetch_csv(UPTREND_CSV_URL)
    sector_df = _fetch_csv(SECTOR_CSV_URL)

    latest_breadth = breadth_df.iloc[-1]
    date_col = "Date" if "Date" in breadth_df.columns else breadth_df.columns[0]
    breadth_date = str(latest_breadth[date_col])

    b200 = _pct(_safe_float(latest_breadth.get("Breadth_Index_200MA")))
    b8 = _pct(_safe_float(latest_breadth.get("Breadth_Index_8MA")))
    breadth_trend = str(latest_breadth.get("Breadth_200MA_Trend", "unknown"))

    if "worksheet" in uptrend_df.columns:
        uptrend_all = uptrend_df[uptrend_df["worksheet"].astype(str).str.lower() == "all"]
    else:
        uptrend_all = uptrend_df
    latest_uptrend = uptrend_all.iloc[-1]
    uptrend_ratio = _pct(_safe_float(latest_uptrend.get("ratio")))
    uptrend_ma10 = _pct(_safe_float(latest_uptrend.get("ma_10")))
    uptrend_slope = _safe_float(latest_uptrend.get("slope")) or 0.0
    uptrend_trend = str(latest_uptrend.get("trend", "unknown"))
    uptrend_color = "GREEN" if uptrend_trend.lower() in ("up", "uptrend", "1") else (
        "RED" if uptrend_trend.lower() in ("down", "downtrend", "-1") else "UNKNOWN"
    )

    sectors = []
    for _, row in sector_df.iterrows():
        ratio = _pct(_safe_float(row.get("Ratio")))
        sectors.append({
            "sector": str(row.get("Sector", "")).strip(),
            "ratio": round(ratio, 1) if ratio is not None else None,
            "trend": str(row.get("Trend", "")).strip() or None,
            "status": str(row.get("Status", "")).strip() or None,
        })
    uptrend_sectors = [s for s in sectors if (s["trend"] or "").lower() in ("up", "uptrend")]
    downtrend_sectors = [s for s in sectors if (s["trend"] or "").lower() in ("down", "downtrend")]
    overbought_sectors = [s for s in sectors if (s["status"] or "").lower() == "overbought"]
    oversold_sectors = [s for s in sectors if (s["status"] or "").lower() == "oversold"]

    dead_cross = (b8 is not None and b200 is not None and b8 < b200)

    # -- Simplified composite health score (0-100, higher = healthier) --------
    # NOTE: this is a deliberately simplified stand-in for the original
    # 6-component (peak/trough cycle, historical percentile, S&P divergence,
    # backtested bearish-signal flag) weighted model, which needs years of
    # persisted score history this stateless agent doesn't keep. It reuses the
    # same same-day inputs (breadth level, uptrend ratio, sector spread,
    # dead-cross) in an explainable weighted blend.
    score_breadth = b8 if b8 is not None else 50.0
    score_uptrend = min(100.0, (uptrend_ratio / 40.0) * 100.0) if uptrend_ratio is not None else 50.0
    score_sectors = (len(uptrend_sectors) / len(sectors) * 100.0) if sectors else 50.0
    composite = 0.40 * score_breadth + 0.35 * score_uptrend + 0.25 * score_sectors
    if dead_cross:
        composite -= 15.0
    composite = max(0.0, min(100.0, composite))

    zone, exposure = _classify_zone(composite, _BREADTH_ZONES)

    return {
        "breadth_date": breadth_date,
        "breadth_200ma_pct": round(b200, 2) if b200 is not None else None,
        "breadth_8ma_pct": round(b8, 2) if b8 is not None else None,
        "breadth_trend": breadth_trend,
        "dead_cross": dead_cross,
        "uptrend_date": str(latest_uptrend.get("date", "")),
        "uptrend_ratio_pct": round(uptrend_ratio, 2) if uptrend_ratio is not None else None,
        "uptrend_ma10_pct": round(uptrend_ma10, 2) if uptrend_ma10 is not None else None,
        "uptrend_slope": round(uptrend_slope, 4),
        "uptrend_color": uptrend_color,
        "sector_summary": {
            "overbought": [s["sector"] for s in overbought_sectors],
            "oversold": [s["sector"] for s in oversold_sectors],
            "uptrend": [s["sector"] for s in uptrend_sectors],
            "downtrend": [s["sector"] for s in downtrend_sectors],
            "all_sectors": sectors,
        },
        "composite_breadth_score": round(composite, 1),
        "health_zone": zone,
        "suggested_equity_exposure": exposure,
        "data_source": "TraderMonty public CSV (GitHub Pages, no API key)",
        "methodology_note": "Simplified adaptation of market-breadth-analyzer / "
                             "uptrend-analyzer / breadth-chart-analyst / sector-analyst; "
                             "not the original backtested multi-component model.",
    }


@tool
def get_market_breadth() -> str:
    """
    Assess overall US market breadth health: how broadly the current rally or
    decline is participated in across stocks and sectors.

    Combines three free, no-API-key TraderMonty datasets:
    - S&P 500 breadth index (% of stocks above key MAs, 8-day vs 200-day MA)
    - US market uptrend stock ratio (~2,800 stocks, 11 sectors)
    - Sector-level uptrend ratios (cyclical vs defensive rotation, overbought/oversold sectors)

    Returns a 0-100 composite breadth health score with a zone classification
    (Strong/Healthy/Neutral/Weakening/Critical) and suggested equity exposure
    range, plus the raw underlying readings and sector breakdown.

    Use this for: "is the rally broad-based?", "how healthy is market breadth?",
    "which sectors are leading/lagging?", "is the market internally weak even
    if the index is near highs?"

    Returns:
        JSON string with breadth/uptrend/sector data and composite score.
    """
    try:
        return json.dumps(_market_breadth_data(), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2 - Distribution Days + Follow-Through Day
#          (merges: ibd-distribution-day-monitor, ftd-detector)
# ─────────────────────────────────────────────────────────────────────────────

def _distribution_days_for_symbol(symbol: str, lookback_days: int = 80) -> dict:
    hist = yf.Ticker(symbol).history(period="1y")
    if hist.empty or len(hist) < 30:
        return {"symbol": symbol, "error": "insufficient price history"}
    hist = hist.tail(lookback_days + 5)

    closes = hist["Close"].values
    volumes = hist["Volume"].values
    date_labels = [d.strftime("%Y-%m-%d") for d in hist.index]

    active_dds = []
    for i in range(1, len(closes)):
        pct_chg = (closes[i] - closes[i - 1]) / closes[i - 1] * 100.0
        if pct_chg <= -0.2 and volumes[i] > volumes[i - 1]:
            active_dds.append({"index": i, "date": date_labels[i], "pct_change": round(float(pct_chg), 2)})

    latest_idx = len(closes) - 1
    for dd in active_dds:
        age = latest_idx - dd["index"]
        high_since = float(np.max(closes[dd["index"]:])) if dd["index"] <= latest_idx else closes[dd["index"]]
        dd_close = float(closes[dd["index"]])
        gained_5pct = (high_since - dd_close) / dd_close * 100.0 >= 5.0
        dd["age_sessions"] = age
        dd["invalidated"] = age > 25 or gained_5pct
        dd["gained_5pct_since"] = round((high_since - dd_close) / dd_close * 100.0, 2)

    active = [dd for dd in active_dds if not dd["invalidated"]]
    d5 = sum(1 for dd in active if dd["age_sessions"] <= 5)
    d15 = sum(1 for dd in active if dd["age_sessions"] <= 15)
    d25 = sum(1 for dd in active if dd["age_sessions"] <= 25)

    ema21 = pd.Series(closes).ewm(span=21, adjust=False).mean().iloc[-1]
    sma50 = pd.Series(closes).rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
    below_key_ma = closes[-1] < ema21 or (sma50 is not None and closes[-1] < sma50)

    if d25 >= 6 or d15 >= 4 or (below_key_ma and d25 >= 5):
        risk = "SEVERE"
    elif d25 >= 5 or d15 >= 3 or d5 >= 2:
        risk = "HIGH"
    elif d25 >= 3:
        risk = "CAUTION"
    else:
        risk = "NORMAL"

    return {
        "symbol": symbol,
        "as_of": date_labels[-1],
        "d5_count": d5, "d15_count": d15, "d25_count": d25,
        "below_21ema_or_50sma": bool(below_key_ma),
        "risk": risk,
        "active_distribution_days": [
            {"date": dd["date"], "pct_change": dd["pct_change"], "age_sessions": dd["age_sessions"]}
            for dd in active
        ],
    }


def _ftd_status_for_symbol(symbol: str, lookback_days: int = 90) -> dict:
    hist = yf.Ticker(symbol).history(period="6mo")
    if hist.empty or len(hist) < 30:
        return {"symbol": symbol, "error": "insufficient price history"}
    hist = hist.tail(lookback_days).reset_index()
    closes = hist["Close"].values
    volumes = hist["Volume"].values
    dates = [d.strftime("%Y-%m-%d") for d in hist["Date"]]

    # Find most recent swing low (min close) in the window
    low_idx = int(np.argmin(closes))
    swing_low = float(closes[low_idx])
    prior_high = float(np.max(closes[:max(low_idx, 1)])) if low_idx > 0 else swing_low
    decline_pct = (swing_low - prior_high) / prior_high * 100.0 if prior_high else 0.0

    days_since_low = len(closes) - 1 - low_idx

    if low_idx == len(closes) - 1:
        return {
            "symbol": symbol, "state": "NO_SIGNAL_YET",
            "note": "Price is at the lookback-window low as of today; no rally attempt to evaluate.",
        }
    if decline_pct > -3.0:
        state = "NO_QUALIFYING_CORRECTION"
        return {
            "symbol": symbol, "state": state,
            "swing_low_date": dates[low_idx], "decline_from_prior_high_pct": round(decline_pct, 2),
            "note": "No 3%+ decline into the swing low; FTD framework doesn't apply (see market breadth/top tools instead).",
        }

    ftd = None
    scan_start = low_idx + 4
    scan_end = min(low_idx + 10, len(closes) - 1)
    for i in range(scan_start, scan_end + 1):
        pct_chg = (closes[i] - closes[i - 1]) / closes[i - 1] * 100.0
        if pct_chg >= 1.25 and volumes[i] > volumes[i - 1]:
            day_number = i - low_idx
            gain_bonus = min(30.0, (pct_chg - 1.25) * 15.0)
            day_bonus = 20.0 if day_number <= 5 else (10.0 if day_number <= 7 else 0.0)
            quality = round(min(100.0, 50.0 + gain_bonus + day_bonus), 1)
            ftd = {
                "date": dates[i], "day_number_of_rally": day_number,
                "pct_gain": round(float(pct_chg), 2), "quality_score": quality,
            }
            break

    if ftd is None:
        if days_since_low > 10 and closes[-1] < swing_low:
            state = "RALLY_FAILED"
        elif days_since_low > 10:
            state = "NO_FTD_CONFIRMED"
        else:
            state = "RALLY_ATTEMPT_IN_PROGRESS"
        return {
            "symbol": symbol, "state": state,
            "swing_low_date": dates[low_idx], "swing_low_price": round(swing_low, 2),
            "days_since_swing_low": days_since_low,
        }

    ftd_idx = low_idx + ftd["day_number_of_rally"]
    ftd_day_low = float(hist["Low"].iloc[ftd_idx])
    invalidated = bool(np.any(closes[ftd_idx + 1:] < ftd_day_low)) if ftd_idx + 1 < len(closes) else False
    quality = ftd["quality_score"]
    if invalidated:
        quality = max(0.0, quality - 40.0)
        state = "FTD_INVALIDATED"
    else:
        state = "FTD_CONFIRMED"

    if quality >= 80:
        exposure = "75-100%"
    elif quality >= 60:
        exposure = "50-75%"
    elif quality >= 40:
        exposure = "25-50%"
    else:
        exposure = "0-25%"

    return {
        "symbol": symbol, "state": state,
        "swing_low_date": dates[low_idx], "swing_low_price": round(swing_low, 2),
        "ftd_date": ftd["date"], "ftd_pct_gain": ftd["pct_gain"],
        "ftd_day_number": ftd["day_number_of_rally"], "ftd_day_low": round(ftd_day_low, 2),
        "quality_score": quality, "suggested_equity_exposure": exposure,
    }


@tool
def get_market_timing_signals(symbols: str = "SPY,QQQ") -> str:
    """
    Detect O'Neil-style market timing signals: Distribution Days (institutional
    selling accumulation, a topping/defensive signal) and Follow-Through Days
    (rally confirmation after a correction, a bottoming/offensive signal).

    For each symbol, computes:
    - Distribution Day counts (d5/d15/d25 = active count within N elapsed
      sessions) and a NORMAL/CAUTION/HIGH/SEVERE risk classification with
      suggested leveraged-ETF (e.g. TQQQ) exposure guidance.
    - Follow-Through Day state machine: swing low -> rally attempt -> FTD
      window (day 4-10) -> FTD confirmed/invalidated, with a 0-100 quality
      score and suggested equity exposure for re-entry after a correction.

    Use this after market close, before changing leveraged exposure, when
    assessing whether an uptrend looks vulnerable, or when asking "has the
    market bottomed / is it safe to buy again?"

    Args:
        symbols: Comma-separated symbols, typically index proxies
                 (default "SPY,QQQ"). Works for any ticker.

    Returns:
        JSON with per-symbol distribution_days and follow_through_day sections.
    """
    try:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:5]
        results = []
        for sym in syms:
            results.append({
                "symbol": sym,
                "distribution_days": _distribution_days_for_symbol(sym),
                "follow_through_day": _ftd_status_for_symbol(sym),
            })
        risk_rank = {"NORMAL": 0, "CAUTION": 1, "HIGH": 2, "SEVERE": 3}
        risks = [r["distribution_days"].get("risk", "NORMAL") for r in results if "risk" in r["distribution_days"]]
        overall_risk = max(risks, key=lambda r: risk_rank.get(r, 0)) if risks else "UNKNOWN"
        return json.dumps({
            "symbols": syms,
            "overall_distribution_risk": overall_risk,
            "results": results,
            "methodology_note": "Adapted from ibd-distribution-day-monitor / ftd-detector using "
                                 "yfinance OHLCV instead of FMP; not trade execution advice.",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3 - Macro Regime Detector (cross-asset ratio analysis)
# ─────────────────────────────────────────────────────────────────────────────

def _series_trend(series: pd.Series) -> str:
    """Rising/Falling/Flat based on recent 20d SMA vs ~6mo (120d) SMA."""
    if len(series) < 40:
        return "unknown"
    short = series.rolling(20).mean().iloc[-1]
    long_ = series.rolling(min(120, len(series) - 1)).mean().iloc[-1]
    if short is None or long_ is None or long_ == 0:
        return "unknown"
    diff_pct = (short - long_) / long_ * 100.0
    if diff_pct > 1.0:
        return "rising"
    if diff_pct < -1.0:
        return "falling"
    return "flat"


@tool
def get_macro_regime() -> str:
    """
    Detect the current structural macro regime (1-2 year horizon) using
    cross-asset ETF ratio analysis: market concentration (RSP/SPY), size
    factor (IWM/SPY), credit conditions (HYG/LQD), equity-bond relationship
    (SPY/TLT + rolling correlation), and sector rotation (XLY/XLP), plus the
    10Y-2Y Treasury yield curve when FRED data is available.

    Classifies the regime as one of: Concentration (mega-cap leadership,
    narrow market), Broadening (expanding participation), Contraction (credit
    tightening / risk-off), Inflationary (stocks and bonds moving together,
    traditional hedging fails), or Transitional (mixed signals).

    Use this for long-term/structural positioning questions, not short-term
    timing (use get_market_timing_signals or get_market_breadth for that).

    Returns:
        JSON with each component's ratio, trend, and the overall regime call.
    """
    try:
        tickers = ["RSP", "SPY", "IWM", "HYG", "LQD", "TLT", "XLY", "XLP"]
        data = yf.download(tickers, period="14mo", auto_adjust=True, progress=False)["Close"]
        data = data.dropna()
        if data.empty or len(data) < 60:
            return json.dumps({"error": "Insufficient ETF price history to compute macro regime."})

        concentration_ratio = data["RSP"] / data["SPY"]
        size_ratio = data["IWM"] / data["SPY"]
        credit_ratio = data["HYG"] / data["LQD"]
        eq_bond_ratio = data["SPY"] / data["TLT"]
        sector_ratio = data["XLY"] / data["XLP"]

        spy_ret = data["SPY"].pct_change().dropna()
        tlt_ret = data["TLT"].pct_change().dropna()
        eq_bond_corr = float(spy_ret.tail(60).corr(tlt_ret.tail(60))) if len(spy_ret) >= 60 else None

        components = {
            "market_concentration": {"ratio": "RSP/SPY", "value": round(float(concentration_ratio.iloc[-1]), 4),
                                      "trend": _series_trend(concentration_ratio),
                                      "interpretation": "rising = broadening (small/mega-cap gap narrowing), falling = concentration"},
            "size_factor": {"ratio": "IWM/SPY", "value": round(float(size_ratio.iloc[-1]), 4),
                             "trend": _series_trend(size_ratio),
                             "interpretation": "rising = small-cap rotation, falling = large-cap leadership"},
            "credit_conditions": {"ratio": "HYG/LQD", "value": round(float(credit_ratio.iloc[-1]), 4),
                                   "trend": _series_trend(credit_ratio),
                                   "interpretation": "falling = credit tightening / risk-off"},
            "equity_bond": {"ratio": "SPY/TLT", "value": round(float(eq_bond_ratio.iloc[-1]), 4),
                             "trend": _series_trend(eq_bond_ratio),
                             "rolling_60d_correlation": round(eq_bond_corr, 3) if eq_bond_corr is not None else None,
                             "interpretation": "positive correlation = stocks & bonds move together (inflationary regime, hedging fails)"},
            "sector_rotation": {"ratio": "XLY/XLP", "value": round(float(sector_ratio.iloc[-1]), 4),
                                 "trend": _series_trend(sector_ratio),
                                 "interpretation": "rising = cyclical/growth appetite, falling = defensive rotation"},
        }

        try:
            from mcp_server import _get_economic_indicators
            fred = _get_economic_indicators("treasury_10y,treasury_2y")
            t10 = fred.get("treasury_10y", {}).get("value")
            t2 = fred.get("treasury_2y", {}).get("value")
            if t10 is not None and t2 is not None:
                spread = round(t10 - t2, 2)
                components["yield_curve"] = {
                    "spread_10y_2y": spread,
                    "state": "inverted" if spread < 0 else ("flat" if spread < 0.25 else "normal"),
                    "interpretation": "inverted/flattening = late-cycle / recession risk rising",
                }
        except Exception:
            pass  # yield curve optional; regime call falls back to the 5 ETF ratios

        votes = {"Broadening": 0, "Concentration": 0, "Contraction": 0, "Inflationary": 0}
        if components["market_concentration"]["trend"] == "rising":
            votes["Broadening"] += 1
        elif components["market_concentration"]["trend"] == "falling":
            votes["Concentration"] += 1
        if components["size_factor"]["trend"] == "rising":
            votes["Broadening"] += 1
        elif components["size_factor"]["trend"] == "falling":
            votes["Concentration"] += 1
        if components["credit_conditions"]["trend"] == "falling":
            votes["Contraction"] += 1
        if components["sector_rotation"]["trend"] == "falling":
            votes["Contraction"] += 1
        if eq_bond_corr is not None and eq_bond_corr > 0.3:
            votes["Inflationary"] += 2
        if "yield_curve" in components and components["yield_curve"]["state"] == "inverted":
            votes["Contraction"] += 1

        top_regime, top_votes = max(votes.items(), key=lambda kv: kv[1])
        regime = top_regime if top_votes >= 2 else "Transitional"

        return json.dumps({
            "as_of": str(data.index[-1].date()),
            "regime": regime,
            "regime_votes": votes,
            "components": components,
            "methodology_note": "Simplified adaptation of macro-regime-detector using yfinance ETF "
                                 "ratios instead of FMP; yield curve included only when FRED_API_KEY is set.",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4 - Market Risk / Top-Bubble Assessment
#          (merges: market-top-detector, us-market-bubble-detector - quant parts)
# ─────────────────────────────────────────────────────────────────────────────

_RISK_ZONES = [
    (81, "Critical", "20-35%"),
    (61, "Red / High Probability Top", "40-55%"),
    (41, "Orange / Elevated Risk", "60-75%"),
    (21, "Yellow / Early Warning", "80-90%"),
    (0, "Green / Normal", "100%"),
]


@tool
def assess_market_risk() -> str:
    """
    Composite market top / bubble-risk score (0-100, higher = riskier) blending
    Distribution Day counts, market breadth health, VIX complacency, and
    defensive sector rotation into a single tactical (2-8 week) risk read.

    This is a quantitative-only adaptation of market-top-detector and
    us-market-bubble-detector: it does NOT include Put/Call ratio, margin
    debt, or IPO-market data (those aren't available via free APIs). For a
    fuller picture, supplement with a news/web search for "CBOE put call
    ratio" and "FINRA margin debt latest" before making a final call.

    Use this when the user asks "is the market topping?", "should I take
    profits?", "is this a bubble?", or "how risky does the market look right now?"

    Returns:
        JSON with the composite score, risk zone, suggested risk budget, and
        each component's contribution.
    """
    try:
        breadth = _market_breadth_data()
        dd_spy = _distribution_days_for_symbol("SPY")
        dd_qqq = _distribution_days_for_symbol("QQQ")

        vix_hist = yf.Ticker("^VIX").history(period="6mo")
        vix_current = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else None
        vix_percentile = None
        if vix_current is not None and len(vix_hist) > 20:
            vix_percentile = float((vix_hist["Close"] < vix_current).mean() * 100.0)

        dd_score_map = {"NORMAL": 0.0, "CAUTION": 25.0, "HIGH": 60.0, "SEVERE": 90.0}
        dd_component = max(
            dd_score_map.get(dd_spy.get("risk", "NORMAL"), 0.0),
            dd_score_map.get(dd_qqq.get("risk", "NORMAL"), 0.0),
        )

        breadth_component = max(0.0, 100.0 - breadth["composite_breadth_score"])

        if vix_percentile is not None and vix_percentile < 10:
            vix_component = 80.0
        elif vix_percentile is not None and vix_percentile < 25:
            vix_component = 40.0
        elif vix_percentile is not None:
            vix_component = max(0.0, 25.0 - vix_percentile * 0.2)
        else:
            vix_component = 0.0

        try:
            xly = yf.Ticker("XLY").history(period="3mo")["Close"]
            xlp = yf.Ticker("XLP").history(period="3mo")["Close"]
            ratio = xly / xlp
            defensive_rotation = ratio.iloc[-1] < ratio.rolling(20).mean().iloc[-1]
            sector_component = 60.0 if defensive_rotation else 0.0
        except Exception:
            sector_component = 0.0

        composite = (0.35 * dd_component + 0.25 * breadth_component
                     + 0.20 * vix_component + 0.20 * sector_component)
        composite = round(max(0.0, min(100.0, composite)), 1)
        zone, risk_budget = _classify_zone(composite, _RISK_ZONES)

        return json.dumps({
            "composite_risk_score": composite,
            "risk_zone": zone,
            "suggested_risk_budget": risk_budget,
            "components": {
                "distribution_days": {"score": dd_component, "spy_risk": dd_spy.get("risk"), "qqq_risk": dd_qqq.get("risk")},
                "breadth_divergence": {"score": round(breadth_component, 1), "breadth_health_score": breadth["composite_breadth_score"]},
                "vix_complacency": {"score": round(vix_component, 1), "vix": round(vix_current, 2) if vix_current else None,
                                     "vix_6mo_percentile": round(vix_percentile, 1) if vix_percentile is not None else None},
                "defensive_sector_rotation": {"score": sector_component},
            },
            "missing_inputs_to_supplement_via_search": ["CBOE equity Put/Call ratio", "FINRA margin debt YoY %"],
            "methodology_note": "Simplified adaptation of market-top-detector / us-market-bubble-detector "
                                 "quantitative components; not a full replacement for either.",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5 - Downtrend Duration Analyzer
# ─────────────────────────────────────────────────────────────────────────────

def _market_cap_tier(market_cap: Optional[float]) -> str:
    if not market_cap:
        return "Unknown"
    if market_cap >= 200e9:
        return "Mega"
    if market_cap >= 10e9:
        return "Large"
    if market_cap >= 2e9:
        return "Mid"
    return "Small"


@tool
def analyze_downtrend_durations(tickers: str, lookback_years: int = 5, window: int = 20) -> str:
    """
    Analyze historical peak-to-trough downtrend durations for a list of
    tickers, to set realistic expectations for how long corrections/pullbacks
    typically last (useful for mean-reversion holding periods or stop-loss
    time-outs).

    Identifies local peaks/troughs using a rolling window, computes duration
    (trading days) and depth (%) for each downtrend, and reports summary
    statistics overall and by market-cap tier.

    Args:
        tickers: Comma-separated ticker list, e.g. "AAPL,MSFT,GOOGL" (max 15).
        lookback_years: Years of history to analyze (default 5).
        window: Rolling window (trading days) for peak/trough detection (default 20).

    Returns:
        JSON with summary statistics, by-market-cap-tier breakdown, and the
        individual downtrend episodes found.
    """
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:15]
        all_downtrends = []
        tier_stats: dict = {}

        for sym in ticker_list:
            stock = yf.Ticker(sym)
            hist = stock.history(period=f"{lookback_years}y")
            if hist.empty or len(hist) < window * 2:
                continue
            close = hist["Close"]
            tier = _market_cap_tier(_safe_float(stock.info.get("marketCap")))

            is_peak = (close == close.rolling(window, center=True).max())
            is_trough = (close == close.rolling(window, center=True).min())
            peak_dates = close.index[is_peak.fillna(False)]
            trough_dates = close.index[is_trough.fillna(False)]

            for peak_date in peak_dates:
                later_troughs = trough_dates[trough_dates > peak_date]
                if len(later_troughs) == 0:
                    continue
                trough_date = later_troughs[0]
                peak_price = float(close.loc[peak_date])
                trough_price = float(close.loc[trough_date])
                duration_days = int((close.index.get_loc(trough_date) - close.index.get_loc(peak_date)))
                depth_pct = round((trough_price - peak_price) / peak_price * 100.0, 2)
                if duration_days <= 0 or depth_pct >= 0:
                    continue
                all_downtrends.append({
                    "symbol": sym, "tier": tier,
                    "peak_date": str(peak_date.date()), "trough_date": str(trough_date.date()),
                    "duration_days": duration_days, "depth_pct": depth_pct,
                })

        if not all_downtrends:
            return json.dumps({"error": "No downtrend episodes detected for the given tickers/window."})

        durations = [d["duration_days"] for d in all_downtrends]
        summary = {
            "total_downtrends": len(all_downtrends),
            "median_duration_days": int(np.median(durations)),
            "mean_duration_days": round(float(np.mean(durations)), 1),
            "p25_duration_days": int(np.percentile(durations, 25)),
            "p75_duration_days": int(np.percentile(durations, 75)),
            "p90_duration_days": int(np.percentile(durations, 90)),
        }

        by_tier: dict = {}
        for tier in ("Mega", "Large", "Mid", "Small", "Unknown"):
            tier_durations = [d["duration_days"] for d in all_downtrends if d["tier"] == tier]
            if tier_durations:
                by_tier[tier] = {
                    "count": len(tier_durations),
                    "median_days": int(np.median(tier_durations)),
                    "mean_days": round(float(np.mean(tier_durations)), 1),
                }

        return json.dumps({
            "tickers_analyzed": ticker_list,
            "lookback_years": lookback_years,
            "summary": summary,
            "by_market_cap_tier": by_tier,
            "downtrends": sorted(all_downtrends, key=lambda d: d["duration_days"], reverse=True)[:30],
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 6 - FinViz Screener URL Builder
# ─────────────────────────────────────────────────────────────────────────────

_FINVIZ_VIEWS = {
    "overview": "111", "valuation": "121", "ownership": "131",
    "performance": "141", "financial": "161", "technical": "171", "custom": "152",
}


@tool
def build_finviz_screener_url(filters: str, view: str = "overview", order: str = "") -> str:
    """
    Build a FinViz stock screener URL from a comma-separated list of FinViz
    filter codes (no API key or browser needed). Use this after translating a
    natural-language screening request (e.g. "high dividend small caps",
    "oversold large caps near 52w low") into FinViz filter codes yourself --
    this tool only assembles the URL, it does not interpret intent.

    Common filter code families: `cap_*` (market cap), `fa_*` (fundamentals,
    e.g. `fa_div_o3` = dividend yield > 3%, `fa_pe_u20` = P/E < 20),
    `ta_*` (technicals, e.g. `ta_rsi_os30` = RSI oversold, `ta_sma50_pa` =
    price above 50-day SMA), `sec_*`/`ind_*` (sector/industry), `sh_*`
    (shares/ownership, e.g. `sh_insidertrans_verypos`), `geo_*` (geography).

    Args:
        filters: Comma-separated FinViz filter codes, e.g.
                 "cap_small,fa_div_o3,fa_pe_u20,geo_usa".
        view: One of overview, valuation, ownership, performance, financial,
              technical, custom (default "overview").
        order: Optional sort field, e.g. "-marketcap", "dividendyield", "-change".

    Returns:
        JSON with the constructed URL and applied filters for user confirmation.
    """
    try:
        filter_list = [f.strip() for f in filters.split(",") if f.strip()]
        if not filter_list:
            return json.dumps({"error": "At least one filter code is required."})
        view_code = _FINVIZ_VIEWS.get(view.lower(), "111")
        url = f"https://finviz.com/screener.ashx?v={view_code}&f={','.join(filter_list)}"
        if order:
            url += f"&o={order}"
        return json.dumps({
            "url": url, "view": view, "filters_applied": filter_list, "sort_order": order or None,
            "note": "Public FinViz screener (no login required for basic filters); "
                    "some filter codes require a FinViz Elite subscription to view full results.",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 7 - Position Sizer
# ─────────────────────────────────────────────────────────────────────────────

@tool
def calculate_position_size(
    account_size: float,
    entry_price: float,
    stop_price: Optional[float] = None,
    atr: Optional[float] = None,
    atr_multiplier: float = 2.0,
    risk_pct: float = 1.0,
    win_rate: Optional[float] = None,
    avg_win_pct: Optional[float] = None,
    avg_loss_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    max_sector_pct: Optional[float] = None,
    current_sector_exposure_pct: float = 0.0,
) -> str:
    """
    Calculate a risk-based share count for a long stock trade using one or
    more sizing methods, then apply portfolio concentration constraints and
    return the final (most conservative) recommended size.

    Methods (all computed when inputs are available, for comparison):
    - Fixed Fractional: risk `risk_pct`% of account on (entry - stop).
    - ATR-Based: stop distance = atr * atr_multiplier, same risk_pct sizing.
    - Kelly Criterion (half-Kelly applied): from win_rate/avg_win_pct/avg_loss_pct,
      sized against (entry - stop) if stop_price or atr is also given.

    Args:
        account_size: Total account equity in dollars.
        entry_price: Planned entry price.
        stop_price: Stop-loss price (for Fixed Fractional method).
        atr: Average True Range value (for ATR-based method).
        atr_multiplier: ATR multiple for stop distance (default 2.0).
        risk_pct: % of account to risk per trade (default 1.0, i.e. 1%).
        win_rate: Historical win rate 0-1 (for Kelly method).
        avg_win_pct: Average winning trade % (for Kelly method).
        avg_loss_pct: Average losing trade % as a positive number (for Kelly method).
        max_position_pct: Optional cap on position value as % of account.
        max_sector_pct: Optional cap on sector exposure as % of account.
        current_sector_exposure_pct: Current exposure to this trade's sector, % of account.

    Returns:
        JSON with each computed method, applied constraints, and the final
        recommended share count / dollar risk.
    """
    try:
        calculations: dict = {}

        risk_per_share_ff = None
        if stop_price is not None and entry_price > stop_price:
            risk_per_share_ff = entry_price - stop_price
            dollar_risk = account_size * risk_pct / 100.0
            shares = int(dollar_risk // risk_per_share_ff)
            calculations["fixed_fractional"] = {
                "shares": shares, "risk_per_share": round(risk_per_share_ff, 2),
                "dollar_risk": round(shares * risk_per_share_ff, 2), "stop_price": stop_price,
            }

        risk_per_share_atr = None
        if atr is not None and atr > 0:
            risk_per_share_atr = atr * atr_multiplier
            implied_stop = round(entry_price - risk_per_share_atr, 2)
            dollar_risk = account_size * risk_pct / 100.0
            shares = int(dollar_risk // risk_per_share_atr)
            calculations["atr_based"] = {
                "shares": shares, "risk_per_share": round(risk_per_share_atr, 2),
                "dollar_risk": round(shares * risk_per_share_atr, 2), "implied_stop_price": implied_stop,
            }

        if win_rate is not None and avg_win_pct is not None and avg_loss_pct is not None and avg_loss_pct > 0:
            b = avg_win_pct / avg_loss_pct
            kelly = win_rate - (1 - win_rate) / b
            half_kelly = max(0.0, kelly / 2.0)
            kelly_dollar_risk = account_size * half_kelly
            entry = {
                "kelly_fraction": round(kelly, 4), "half_kelly_fraction": round(half_kelly, 4),
                "half_kelly_risk_pct_of_account": round(half_kelly * 100.0, 2),
                "half_kelly_dollar_risk": round(kelly_dollar_risk, 2),
            }
            risk_per_share = risk_per_share_ff or risk_per_share_atr
            if risk_per_share:
                entry["shares"] = int(kelly_dollar_risk // risk_per_share)
            calculations["kelly"] = entry

        if not calculations:
            return json.dumps({"error": "Provide at least stop_price, atr, or win_rate/avg_win_pct/avg_loss_pct."})

        candidate_shares = {k: v["shares"] for k, v in calculations.items() if "shares" in v}
        if not candidate_shares:
            return json.dumps({"calculations": calculations, "note": "Kelly sizing computed but no entry/stop given for share count."})

        method, shares = min(candidate_shares.items(), key=lambda kv: kv[1]) if len(candidate_shares) > 1 else next(iter(candidate_shares.items()))
        constraints_applied = []
        binding_constraint = None

        if max_position_pct is not None:
            max_shares_by_position = int((account_size * max_position_pct / 100.0) // entry_price)
            if max_shares_by_position < shares:
                shares = max_shares_by_position
                binding_constraint = "max_position_pct"
            constraints_applied.append({"type": "max_position_pct", "limit_pct": max_position_pct, "max_shares": max_shares_by_position})

        if max_sector_pct is not None:
            available_sector_room_pct = max(0.0, max_sector_pct - current_sector_exposure_pct)
            max_shares_by_sector = int((account_size * available_sector_room_pct / 100.0) // entry_price)
            if max_shares_by_sector < shares:
                shares = max_shares_by_sector
                binding_constraint = "max_sector_pct"
            constraints_applied.append({"type": "max_sector_pct", "available_room_pct": round(available_sector_room_pct, 2), "max_shares": max_shares_by_sector})

        shares = max(0, shares)
        final_position_value = round(shares * entry_price, 2)
        final_risk_dollars = round(shares * (risk_per_share_ff or risk_per_share_atr or 0), 2)

        return json.dumps({
            "parameters": {"account_size": account_size, "entry_price": entry_price, "risk_pct": risk_pct},
            "calculations": calculations,
            "constraints_applied": constraints_applied,
            "sizing_method_before_constraints": method,
            "binding_constraint": binding_constraint,
            "final_recommended_shares": shares,
            "final_position_value": final_position_value,
            "final_risk_dollars": final_risk_dollars,
            "final_risk_pct_of_account": round(final_risk_dollars / account_size * 100.0, 2) if account_size else None,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 8 - Options Strategy Advisor (Black-Scholes)
# ─────────────────────────────────────────────────────────────────────────────

def _bs_price_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str, q: float = 0.0) -> dict:
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
        return {"price": intrinsic, "delta": 1.0 if (option_type == "call" and S > K) else 0.0,
                "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "call":
        price = S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        delta = math.exp(-q * T) * _norm_cdf(d1)
        theta = ((-S * _norm_pdf(d1) * sigma * math.exp(-q * T) / (2 * math.sqrt(T))
                  - r * K * math.exp(-r * T) * _norm_cdf(d2)
                  + q * S * _norm_cdf(d1) * math.exp(-q * T)) / 365.0)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)
        delta = math.exp(-q * T) * (_norm_cdf(d1) - 1.0)
        theta = ((-S * _norm_pdf(d1) * sigma * math.exp(-q * T) / (2 * math.sqrt(T))
                  + r * K * math.exp(-r * T) * _norm_cdf(-d2)
                  - q * S * _norm_cdf(-d1) * math.exp(-q * T)) / 365.0)
    gamma = math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T) / 100.0
    return {"price": round(price, 4), "delta": round(delta, 4), "gamma": round(gamma, 5),
            "theta": round(theta, 4), "vega": round(vega, 4)}


_STRATEGY_LEGS = {
    # name -> list of (option_type|'stock', strike_key, position: 1 long / -1 short)
    # Convention: "strike" < "strike2" < "strike3" < "strike4" (ascending) for
    # every strategy that uses more than one strike.
    "long_call": [("call", "strike", 1)],
    "long_put": [("put", "strike", 1)],
    "covered_call": [("stock", None, 1), ("call", "strike", -1)],
    "protective_put": [("stock", None, 1), ("put", "strike", 1)],
    "bull_call_spread": [("call", "strike", 1), ("call", "strike2", -1)],       # buy lower call, sell higher call
    "bear_put_spread": [("put", "strike2", 1), ("put", "strike", -1)],          # buy higher put, sell lower put
    "bull_put_spread": [("put", "strike2", -1), ("put", "strike", 1)],         # sell higher put, buy lower put (credit)
    "bear_call_spread": [("call", "strike", -1), ("call", "strike2", 1)],       # sell lower call, buy higher call (credit)
    "long_straddle": [("call", "strike", 1), ("put", "strike", 1)],
    "long_strangle": [("put", "strike", 1), ("call", "strike2", 1)],            # buy lower put + higher call
    "iron_condor": [("put", "strike", 1), ("put", "strike2", -1),
                     ("call", "strike3", -1), ("call", "strike4", 1)],          # long put < short put < short call < long call
}


def _default_strikes(strategy: str, S: float) -> dict:
    """Strategy-aware default strikes (all four keys always populated)."""
    d = {"strike": round(S * 0.95, 2), "strike2": round(S * 1.05, 2),
         "strike3": round(S * 1.05, 2), "strike4": round(S * 1.10, 2)}
    if strategy in ("long_call", "long_put", "protective_put", "long_straddle"):
        d["strike"] = round(S, 2)
    elif strategy == "covered_call":
        d["strike"] = round(S * 1.05, 2)
    elif strategy == "bull_call_spread":
        d["strike"], d["strike2"] = round(S * 0.97, 2), round(S * 1.05, 2)
    elif strategy == "bear_put_spread":
        d["strike"], d["strike2"] = round(S * 0.95, 2), round(S * 1.03, 2)
    elif strategy == "bull_put_spread":
        d["strike"], d["strike2"] = round(S * 0.93, 2), round(S * 1.00, 2)
    elif strategy == "bear_call_spread":
        d["strike"], d["strike2"] = round(S * 1.00, 2), round(S * 1.07, 2)
    elif strategy == "iron_condor":
        d["strike"], d["strike2"] = round(S * 0.90, 2), round(S * 0.95, 2)
        d["strike3"], d["strike4"] = round(S * 1.05, 2), round(S * 1.10, 2)
    return d


@tool
def calculate_option_strategy(
    ticker: str,
    strategy: str,
    days_to_expiration: int = 30,
    strike: Optional[float] = None,
    strike2: Optional[float] = None,
    strike3: Optional[float] = None,
    strike4: Optional[float] = None,
    volatility: Optional[float] = None,
    risk_free_rate: float = 0.05,
    contracts: int = 1,
) -> str:
    """
    Price an options strategy with the Black-Scholes model, compute position
    Greeks, and simulate profit/loss at expiration across a range of stock
    prices to find max profit, max loss, and breakeven(s).

    Supported strategies: long_call, long_put, covered_call, protective_put,
    bull_call_spread, bear_put_spread, bull_put_spread (credit),
    bear_call_spread (credit), long_straddle, long_strangle, iron_condor.
    (Multi-expiration strategies like calendar/diagonal spreads are not covered.)

    If strikes are omitted, reasonable ATM/OTM strikes are auto-generated
    around the current price (+/-5% steps). If volatility (IV) is omitted,
    90-day historical volatility is used instead and flagged as such.

    Args:
        ticker: Underlying stock ticker.
        strategy: One of the supported strategy names above.
        days_to_expiration: Days to expiration (default 30).
        strike, strike2, strike3, strike4: Strike prices; meaning depends on
            strategy (see leg order in the strategy name, e.g. bull_call_spread
            = long `strike` call / short `strike2` call).
        volatility: Implied volatility as a decimal (e.g. 0.25 for 25%). If
            omitted, historical volatility is estimated and used instead.
        risk_free_rate: Annualized risk-free rate as a decimal (default 0.05).
        contracts: Number of contracts (100 shares each), default 1.

    Returns:
        JSON with leg pricing, net debit/credit, position Greeks, max
        profit/loss, breakeven price(s), and a coarse P/L table.
    """
    try:
        strategy = strategy.strip().lower()
        if strategy not in _STRATEGY_LEGS:
            return json.dumps({"error": f"Unsupported strategy '{strategy}'. Supported: {list(_STRATEGY_LEGS.keys())}"})

        stock = yf.Ticker(ticker.upper())
        hist = stock.history(period="6mo")
        if hist.empty:
            return json.dumps({"error": f"No price data for {ticker}"})
        S = float(hist["Close"].iloc[-1])

        hv_note = None
        if volatility is None:
            returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
            volatility = float(returns.std() * math.sqrt(252))
            hv_note = "volatility not provided; using 6mo historical volatility"

        strikes_given = {"strike": strike, "strike2": strike2, "strike3": strike3, "strike4": strike4}
        defaults = _default_strikes(strategy, S)
        strikes = {k: (v if v is not None else defaults[k]) for k, v in strikes_given.items()}

        T = max(days_to_expiration, 1) / 365.0
        legs = _STRATEGY_LEGS[strategy]
        leg_details = []
        net_premium = 0.0  # positive = net debit paid, negative = net credit received

        for opt_type, strike_key, position in legs:
            if opt_type == "stock":
                leg_details.append({"type": "stock", "position": "long" if position > 0 else "short", "price": round(S, 2)})
                continue
            K = strikes[strike_key]
            greeks = _bs_price_greeks(S, K, T, risk_free_rate, volatility, opt_type)
            net_premium += position * greeks["price"]  # long pays (+debit), short receives (-credit)
            leg_details.append({
                "type": opt_type, "strike": K, "position": "long" if position > 0 else "short",
                "theoretical_price": greeks["price"], "delta": greeks["delta"], "gamma": greeks["gamma"],
                "theta": greeks["theta"], "vega": greeks["vega"],
            })

        position_greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        for (opt_type, strike_key, position), detail in zip(legs, leg_details):
            if opt_type == "stock":
                position_greeks["delta"] += position * 1.0
                continue
            for g in ("delta", "gamma", "theta", "vega"):
                position_greeks[g] += position * detail[g]
        for g in position_greeks:
            position_greeks[g] = round(position_greeks[g] * 100 * contracts, 2)

        price_range = np.linspace(S * 0.6, S * 1.4, 161)
        pnl = np.zeros_like(price_range)
        for (opt_type, strike_key, position), detail in zip(legs, leg_details):
            if opt_type == "stock":
                pnl += position * (price_range - S)
                continue
            K = strikes[strike_key]
            intrinsic = np.maximum(0, price_range - K) if opt_type == "call" else np.maximum(0, K - price_range)
            premium = detail["theoretical_price"]
            pnl += position * (intrinsic - premium)
        pnl = pnl * 100 * contracts

        max_profit = float(np.max(pnl))
        max_loss = float(np.min(pnl))
        sign_changes = np.where(np.diff(np.sign(pnl)) != 0)[0]
        breakevens = [round(float(price_range[i] + (price_range[i + 1] - price_range[i]) *
                                   (0 - pnl[i]) / (pnl[i + 1] - pnl[i])), 2) for i in sign_changes] if len(sign_changes) else []

        net_debit_credit = round(net_premium * 100 * contracts, 2)

        return json.dumps({
            "ticker": ticker.upper(), "strategy": strategy, "current_price": round(S, 2),
            "days_to_expiration": days_to_expiration,
            "volatility_used": round(volatility, 4), "volatility_note": hv_note,
            "risk_free_rate": risk_free_rate, "contracts": contracts,
            "legs": leg_details,
            "net_debit_or_credit": net_debit_credit,
            "net_debit_or_credit_label": "debit (paid)" if net_debit_credit > 0 else "credit (received)",
            "position_greeks": position_greeks,
            "max_profit": round(max_profit, 2) if max_profit < 1e8 else "unlimited (capped in simulation range)",
            "max_loss": round(max_loss, 2),
            "breakevens": breakevens,
            "disclaimer": "Theoretical Black-Scholes pricing (European-style); actual market prices, "
                           "American-exercise features, bid-ask spread, and commissions will differ.",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 9 - Pair Trade Screener (correlation + cointegration)
# ─────────────────────────────────────────────────────────────────────────────

@tool
def find_pair_trade_candidates(tickers: str, lookback_days: int = 730, min_correlation: float = 0.70) -> str:
    """
    Screen a user-supplied list of tickers for statistical-arbitrage pair
    trading candidates: computes pairwise correlation, hedge ratio (beta),
    cointegration (Augmented Dickey-Fuller test on the price spread), spread
    half-life, and the current z-score, then ranks tradeable pairs.

    Unlike a full-universe scanner, this takes an explicit ticker list (e.g.
    from screen_stocks or a sector you already have in mind) -- max 12 tickers
    (66 pairs) to bound compute cost.

    Args:
        tickers: Comma-separated tickers, e.g. "AAPL,MSFT,GOOGL,META,NVDA" (max 12).
        lookback_days: Historical lookback in calendar days (default 730 = 2y).
        min_correlation: Minimum Pearson correlation to consider a pair (default 0.70).

    Returns:
        JSON with cointegrated/candidate pairs sorted by statistical strength,
        each with correlation, beta, cointegration p-value, half-life, current
        z-score, and a LONG/SHORT/NONE signal.
    """
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return json.dumps({"error": "statsmodels is required for cointegration testing but is not installed."})

    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:12]
        if len(ticker_list) < 2:
            return json.dumps({"error": "Provide at least 2 tickers."})

        period = f"{max(lookback_days, 90)}d"
        raw = yf.download(ticker_list, period=period, auto_adjust=True, progress=False)["Close"].dropna()
        if raw.empty or len(raw) < 60:
            return json.dumps({"error": "Insufficient overlapping price history for the given tickers."})

        results = []
        for a, b in itertools.combinations(ticker_list, 2):
            if a not in raw.columns or b not in raw.columns:
                continue
            price_a, price_b = raw[a], raw[b]
            corr = float(price_a.corr(price_b))
            if corr < min_correlation:
                continue

            beta = float(np.cov(price_a, price_b)[0, 1] / np.var(price_b))
            spread = price_a - beta * price_b

            try:
                adf_stat, p_value = adfuller(spread, autolag="AIC")[:2]
            except Exception:
                continue

            spread_lag = spread.shift(1).dropna()
            spread_diff = spread.diff().dropna()
            aligned = pd.concat([spread_diff, spread_lag], axis=1).dropna()
            aligned.columns = ["diff", "lag"]
            if len(aligned) < 20 or aligned["lag"].var() == 0:
                half_life = None
            else:
                slope = float(np.cov(aligned["diff"], aligned["lag"])[0, 1] / np.var(aligned["lag"]))
                half_life = round(-math.log(2) / slope, 1) if slope < 0 else None

            recent_spread = spread.tail(90)
            mean_s, std_s = recent_spread.mean(), recent_spread.std()
            z_score = round(float((spread.iloc[-1] - mean_s) / std_s), 2) if std_s else 0.0

            if z_score >= 2.0:
                signal = "SHORT_A_LONG_B"
            elif z_score <= -2.0:
                signal = "LONG_A_SHORT_B"
            else:
                signal = "NONE"

            results.append({
                "pair": f"{a}/{b}", "stock_a": a, "stock_b": b,
                "correlation": round(corr, 3), "beta_hedge_ratio": round(beta, 3),
                "cointegration_pvalue": round(float(p_value), 4),
                "cointegrated": bool(p_value < 0.05),
                "half_life_days": half_life,
                "current_zscore": z_score, "signal": signal,
            })

        results.sort(key=lambda r: (not r["cointegrated"], r["cointegration_pvalue"]))
        return json.dumps({
            "tickers_screened": ticker_list, "lookback_days": lookback_days,
            "min_correlation": min_correlation,
            "pairs_found": len(results),
            "pairs": results[:20],
            "methodology_note": "Adapted from pair-trade-screener using yfinance + statsmodels ADF test "
                                 "instead of FMP; transaction costs and borrow fees not modeled.",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

ALL_MARKET_TOOLS = [
    get_market_breadth,
    get_market_timing_signals,
    get_macro_regime,
    assess_market_risk,
    analyze_downtrend_durations,
    build_finviz_screener_url,
    calculate_position_size,
    calculate_option_strategy,
    find_pair_trade_candidates,
]
