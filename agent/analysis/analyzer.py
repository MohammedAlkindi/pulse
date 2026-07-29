"""Claude-powered analysis layer.

Sends a week's events to Claude and returns a structured analysis dict.
Tool-use enforces the output schema so downstream code can rely on it.

Assumptions:
- If the events list is empty, we still call Claude so it can note data sparsity.
- We trim metadata fields to avoid blowing the context window on large event sets.
  Specifically, 'snippet' is truncated to 120 chars and 'metadata' is passed as-is
  since individual fields are already bounded upstream.
- claude-sonnet-4-6 has a 200k context window; 500 events × ~300 tokens = ~150k tokens,
  which is within budget.  If you regularly exceed this, add chunking here.
"""

import json
import logging

import anthropic

from agent.config import Config
from agent.retry import with_retry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a personal intelligence analyst reviewing one week of activity for a developer.
Analyze the provided events and identify:
  1. What was actually worked on
  2. What patterns or themes emerge
  3. What appears to be drifting or neglected
  4. What deserves attention next week

You are also given COMPUTED MOMENTUM lines derived from multiple weeks of stored
history. Those lines are calculated facts, not model output: ground 'drifting' in the
STALLED and FALLING tracks (name them), and let RISING and NEW tracks inform themes
and next-week attention. Do not claim something is drifting unless the momentum data
or this week's events support it.

Be specific and factual. Every observation must trace to at least one event or
momentum line. Do not invent observations. If data is sparse, say so explicitly in
data_quality_notes.\
"""

_ANALYSIS_TOOL = {
    "name": "record_analysis",
    "description": "Record the structured analysis of the developer's weekly activity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "High-level themes and patterns observed across all sources.",
            },
            "active_projects": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Projects or areas that saw meaningful activity this week.",
            },
            "drifting": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Areas that appear neglected or have slowed vs. recent weeks.",
            },
            "attention_next_week": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific items that deserve focus next week, with reasoning.",
            },
            "data_quality_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Notes on data gaps, disabled sources, or low event volume.",
            },
        },
        "required": ["themes", "active_projects", "drifting", "attention_next_week", "data_quality_notes"],
    },
}

_EMPTY_ANALYSIS: dict = {
    "themes": [],
    "active_projects": [],
    "drifting": [],
    "attention_next_week": [],
    "data_quality_notes": ["No events available for analysis."],
}


def _trim_events(events: list[dict]) -> list[dict]:
    """Trim verbose fields to keep token count reasonable."""
    trimmed = []
    for e in events:
        meta = dict(e.get("metadata", {}))
        if "snippet" in meta and isinstance(meta["snippet"], str):
            meta["snippet"] = meta["snippet"][:120]
        trimmed.append({
            "id": e["id"],
            "source": e["source"],
            "event_type": e["event_type"],
            "title": (e.get("title") or "")[:200],
            "occurred_at": e["occurred_at"],
            "metadata": meta,
        })
    return trimmed


@with_retry(label="Claude analysis", max_attempts=3, retryable=(anthropic.APIError,))
def _call_claude(client: anthropic.Anthropic, model: str, events_json: str,
                 momentum_summary: str | None) -> dict:
    momentum_block = (
        f"COMPUTED MOMENTUM (from stored multi-week history):\n{momentum_summary}\n\n"
        if momentum_summary else ""
    )
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        tools=[_ANALYSIS_TOOL],
        tool_choice={"type": "any"},
        messages=[
            {
                "role": "user",
                "content": f"{momentum_block}Here are this week's events:\n\n{events_json}",
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_analysis":
            return block.input

    # Defensive: should not reach here because tool_choice="any" forces a tool call
    logger.warning("[analyzer] Claude did not call record_analysis; returning empty analysis.")
    return _EMPTY_ANALYSIS


def analyze(events: list[dict], cfg: Config, momentum_summary: str | None = None) -> dict:
    """
    Run Claude analysis on a week's events, grounded in computed momentum.
    Returns the structured analysis dict; never raises — returns empty analysis on failure.
    """
    if not events:
        logger.info("[analyzer] no events; skipping Claude call.")
        return _EMPTY_ANALYSIS

    try:
        api_key = cfg.analysis_api_key()
    except EnvironmentError as exc:
        logger.error("[analyzer] %s", exc)
        return {**_EMPTY_ANALYSIS, "data_quality_notes": [f"Analysis skipped: {exc}"]}

    model = cfg.analysis_model()
    client = anthropic.Anthropic(api_key=api_key)
    events_json = json.dumps(_trim_events(events), indent=2)

    try:
        result = _call_claude(client, model, events_json, momentum_summary)
        logger.info("[analyzer] analysis complete — %d themes, %d active projects",
                    len(result.get("themes", [])), len(result.get("active_projects", [])))
        return result
    except Exception as exc:
        logger.error("[analyzer] Claude call failed after retries: %s", exc)
        return {**_EMPTY_ANALYSIS, "data_quality_notes": [f"Analysis failed: {exc}"]}
