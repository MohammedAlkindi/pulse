"""Persist extracted items across briefings.

Items are durable: a commitment seen last week and mentioned again this
week is the same item with more evidence, not a new row. Matching is
deterministic (kind + token overlap); status changes append to history
and never overwrite it.
"""

import re
import uuid

from agent.analysis.citations import derive_confidence
from agent.store import db

_MATCH_THRESHOLD = 0.5


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(t) > 2}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _find_match(candidate: dict, open_items: list[dict]) -> dict | None:
    best, best_score = None, 0.0
    for item in open_items:
        if item["kind"] != candidate["kind"]:
            continue
        score = similarity(item["text"], candidate["text"])
        if score >= _MATCH_THRESHOLD and score > best_score:
            best, best_score = item, score
    return best


def sync_items(candidates: list[dict], week: str,
               event_index: dict[str, dict] | None = None,
               db_path=None) -> dict:
    """
    Merge this run's candidates into the persistent items ledger.
    Returns {"created": n, "reseen": n}.
    event_index maps event_id -> event row, used for confidence derivation.
    """
    kwargs = {"db_path": db_path} if db_path else {}
    open_items = db.list_items(status="open", **kwargs)
    event_index = event_index or {}

    created = reseen = 0
    for candidate in candidates:
        match = _find_match(candidate, open_items)
        evidence_events = [event_index[e] for e in candidate["evidence"] if e in event_index]

        if match:
            merged_evidence = sorted(set(match["evidence"]) | set(candidate["evidence"]))
            due = candidate.get("due_date") or None
            db.update_item(match["id"], last_week=week, evidence=merged_evidence,
                           due_date=due, **kwargs)
            db.append_item_history(match["id"], week, "seen",
                                   detail=candidate["text"][:200],
                                   evidence=candidate["evidence"], **kwargs)
            match["evidence"] = merged_evidence
            reseen += 1
        else:
            item_id = str(uuid.uuid4())
            item = {
                "id": item_id,
                "kind": candidate["kind"],
                "text": candidate["text"],
                "workstream_id": candidate.get("workstream_id", ""),
                "counterparty": candidate.get("counterparty", ""),
                "due_date": candidate.get("due_date", ""),
                "evidence": candidate["evidence"],
                "confidence": derive_confidence(evidence_events, week),
                "first_week": candidate.get("week", week),
                "last_week": week,
                "trust": candidate.get("trust", "normal"),
            }
            db.insert_item(item, **kwargs)
            db.append_item_history(item_id, week, "created",
                                   detail=candidate["text"][:200],
                                   evidence=candidate["evidence"], **kwargs)
            open_items.append({**item, "status": "open"})
            created += 1
    return {"created": created, "reseen": reseen}


def resolve_item(item_id: str, week: str, note: str = "", db_path=None) -> None:
    """Explicit resolution — preserved as a history entry, never a deletion."""
    kwargs = {"db_path": db_path} if db_path else {}
    db.update_item(item_id, status="resolved", **kwargs)
    db.append_item_history(item_id, week, "status:resolved", detail=note, **kwargs)


def stale_open_items(current_week: str, min_weeks_open: int = 1, db_path=None) -> list[dict]:
    """Open items not re-seen since at least min_weeks_open weeks ago."""
    from agent.analysis.citations import _week_distance
    kwargs = {"db_path": db_path} if db_path else {}
    stale = []
    for item in db.list_items(status="open", **kwargs):
        if _week_distance(item["last_week"], current_week) >= min_weeks_open:
            stale.append(item)
    return stale
