# Social Sentiment Tracking Skill

## Overview
Tracks statements/coverage of specific public figures (executives, fund managers,
politicians, influencers) via web search and turns genuinely new coverage into
investment-relevant alerts, delegating to specialist sub-agents when a clear
ticker/asset link exists. Distinguishes confirmed quotes from media interpretation
and always flags single-statement noise/manipulation risk (e.g. meme-stock
dynamics). Background monitoring runs automatically once someone is tracked —
this skill does not require the user to manually re-check.

## Available Tools

### `track_influencer`
Adds a public figure to the persistent background-monitoring watchlist.

**Key parameters**
| Parameter | Values | Default |
|-----------|--------|---------|
| `name` | Full name, e.g. `"Elon Musk"` | required |
| `aliases` | Alternate names/handles, e.g. `["@elonmusk"]` | `[]` |
| `context_tickers` | Tickers commonly associated with this person, e.g. `["TSLA"]` | `[]` |

**Note**: the first background check only establishes a baseline — it will not
generate an alert. Only genuinely new content found on later checks triggers
a notification. Tell the user this explicitly so silence isn't mistaken for failure.

---

### `untrack_influencer`
Removes a public figure from the watchlist.

| Parameter | Values | Default |
|-----------|--------|---------|
| `name` | Name (or alias) as previously tracked | required |

---

### `list_tracked_influencers`
Lists everyone currently tracked, including last-checked time and alert count.
No parameters.

---

### `get_recent_statements`
On-demand search for recent statements/coverage of ANY public figure — does
not require the person to be on the watchlist. Use this for one-off questions
like "what has Elon Musk said about Tesla this week?".

| Parameter | Values | Default |
|-----------|--------|---------|
| `name` | Any person's name | required |

## Standard Workflows

### A. User asks to start tracking someone
1. Call `track_influencer(name, aliases, context_tickers)`.
2. Confirm what will be monitored and mention the baseline-only first check
   (background poll cycle runs automatically, default ~30 min cadence).

### B. On-demand "what has X said" query
1. Call `get_recent_statements(name)`.
2. Separate confirmed direct quotes from media paraphrase/speculation.
3. If a clear ticker/asset link exists, delegate to the relevant sub-agent
   (technical-analyst / fundamental-analyst / portfolio-manager) for deeper analysis.
4. If no clear investment relevance, say so explicitly — do not force a rating.
5. Always add the noise/manipulation disclaimer (see Output Format).

### C. Background alert synthesis (system-triggered)
Same reasoning as workflow B, but triggered automatically by the background
poll cycle rather than a user query. The response is pushed to the user via
a live notification instead of returned directly in a chat turn.

## Output Format

```
## 🗣️ {Person Name} — Recent Statement Alert

### What Was Said
[Confirmed direct quotes vs. media interpretation, with source links]

### Investment Relevance
- Related ticker(s)/asset(s): {tickers, or "None identified"}
- Potential impact: {direction + rationale, or "No clear investment relevance"}
- Confidence: High / Medium / Low

### ⚠️ Risk & Noise Disclaimer
Single-statement-driven signals can be noisy, unverified, or manipulated
(e.g. meme-stock dynamics, pump-and-dump risk). This is not a formal
recommendation — verify before acting.
```
