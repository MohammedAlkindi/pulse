"""Deterministic extraction of decisions, commitments, deadlines, blockers,
and questions from event text.

This is the measurable stage: pure pattern rules over titles and snippets,
each candidate carrying the exact evidence event id it came from. Source text
is treated strictly as data — an email that says "ignore all instructions"
is just a sentence that matches or doesn't match a pattern.

An optional LLM refinement stage may clean and merge candidates, but its
output passes through the same citation validation and can never introduce
evidence that does not exist.
"""

import re
from datetime import date, datetime, timedelta

from agent.analysis.sanitize import classify_sensitivity, most_severe, sanitize_for_markdown

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("decision", re.compile(
        r"\b(we (decided|agreed)|decided to|decision:|going with|we're going with|let's go with|settled on)\b", re.I)),
    ("commitment_by_user", re.compile(
        r"\b(i(?:'ll| will| can| am going to) (?:send|share|get|write|finish|review|update|deliver|fix|follow up|have)|i'll get back)\b", re.I)),
    ("commitment_by_other", re.compile(
        r"\b(?:he|she|they|we)(?:'ll| will)\s+(?:send|share|get|review|update|deliver|fix|follow up)\b", re.I)),
    ("blocker", re.compile(
        r"\b(blocked (?:on|by)|waiting on|waiting for|stuck on|can't proceed|cannot proceed)\b", re.I)),
    ("question", re.compile(
        r"\b(can you|could you|any update on|what's the status|did you get a chance)\b", re.I)),
]

_DEADLINE_RE = re.compile(
    r"\b(?:by|before|due(?: on| by)?|deadline(?: is)?)\s+"
    r"(?P<phrase>tomorrow|today|end of (?:day|week|month)|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})",
    re.I,
)


def parse_due_phrase(phrase: str, base: datetime) -> str:
    """Resolve a deadline phrase to an ISO date relative to when it was said."""
    p = phrase.lower().strip()
    base_date = base.date()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        return p
    if re.fullmatch(r"\d{1,2}/\d{1,2}", p):
        month, day = (int(x) for x in p.split("/"))
        year = base_date.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return ""
        if candidate < base_date:
            candidate = date(year + 1, month, day)
        return candidate.isoformat()
    if p == "today":
        return base_date.isoformat()
    if p == "tomorrow":
        return (base_date + timedelta(days=1)).isoformat()
    if p == "end of day":
        return base_date.isoformat()
    if p == "end of week":
        friday = base_date + timedelta(days=(4 - base_date.weekday()) % 7)
        return friday.isoformat()
    if p == "end of month":
        nxt = (base_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (nxt - timedelta(days=1)).isoformat()
    if p in _WEEKDAYS:
        target = _WEEKDAYS.index(p)
        delta = (target - base_date.weekday()) % 7 or 7
        return (base_date + timedelta(days=delta)).isoformat()
    return ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _event_text(event: dict) -> str:
    meta = event.get("metadata") or {}
    return f"{event.get('title') or ''}. {meta.get('snippet') or ''}"


def _counterparty(event: dict) -> str:
    if event.get("source") != "gmail":
        return ""
    sender = (event.get("metadata") or {}).get("sender", "")
    name = re.sub(r"<[^>]*>", "", sender).strip().strip('"')
    return name or sender


def _base_dt(event: dict) -> datetime:
    try:
        return datetime.fromisoformat(event.get("occurred_at", ""))
    except ValueError:
        return datetime(1970, 1, 1)


def extract_candidates(events: list[dict], known_domains: set[str] | None = None) -> list[dict]:
    """
    Pure pattern extraction. Each candidate:
      {kind, text, evidence: [event_id], counterparty, due_date, week, trust}
    Direction for commitments comes from the event type: first-person
    commitments in mail the user *sent* are the user's; in received mail
    they belong to the sender. `trust` records whether the source content
    looked hostile, so the briefing can present it as claimed, not settled.
    """
    candidates = []
    for event in events:
        week = event.get("week_number", "")
        sent_by_user = event.get("event_type") == "email_sent"
        trust = most_severe(event.get("sensitivity", ""),
                            classify_sensitivity(event, known_domains))

        for sentence in _sentences(_event_text(event)):
            for kind, pattern in _PATTERNS:
                if not pattern.search(sentence):
                    continue
                resolved_kind = kind
                if kind == "commitment_by_user" and not sent_by_user and event.get("source") == "gmail":
                    resolved_kind = "commitment_by_other"

                due = ""
                deadline_match = _DEADLINE_RE.search(sentence)
                if deadline_match:
                    due = parse_due_phrase(deadline_match.group("phrase"), _base_dt(event))

                candidates.append({
                    "kind": resolved_kind,
                    "text": sanitize_for_markdown(sentence, 300),
                    "evidence": [event["id"]],
                    "counterparty": _counterparty(event),
                    "due_date": due,
                    "week": week,
                    "trust": trust,
                })
                break  # one kind per sentence: first pattern wins

            # A dated sentence with no other pattern is still a deadline signal.
            else:
                deadline_match = _DEADLINE_RE.search(sentence)
                if deadline_match:
                    due = parse_due_phrase(deadline_match.group("phrase"), _base_dt(event))
                    if due:
                        candidates.append({
                            "kind": "deadline",
                            "text": sanitize_for_markdown(sentence, 300),
                            "evidence": [event["id"]],
                            "counterparty": _counterparty(event),
                            "due_date": due,
                            "week": week,
                            "trust": trust,
                        })
    return candidates
