"""Read-mostly JSON API over the local ledger.

Pure functions returning plain dicts, so the same layer serves the HTTP
handler and the tests. Nothing here returns a secret: connector status is
reported through `secrets.describe`, which never includes the value.
"""

from agent import clock, secrets
from agent.analysis.items_sync import stale_open_items
from agent.analysis.momentum import compute_momentum, iso_week_of_now, trailing_weeks
from agent.analysis.sanitize import sanitize_for_markdown
from agent.briefing.changes import approaching_deadlines
from agent.query.ask import ask as ask_pulse
from agent.store import db

SOURCES = ("gmail", "github", "notion")


def _event_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "excerpt": sanitize_for_markdown(str((e.get("metadata") or {}).get("snippet") or (e.get("metadata") or {}).get("description") or ""), 1200),
        "source": e.get("source", ""),
        "type": e.get("event_type", ""),
        "title": sanitize_for_markdown(e.get("title") or "", 200),
        "actor": sanitize_for_markdown(e.get("actor") or "", 80),
        "occurred_at": e.get("occurred_at", ""),
        "url": e.get("canonical_url") or "",
        "workstream_id": e.get("workstream_id", ""),
        "sensitivity": e.get("sensitivity", "normal"),
    }


def _item_view(i: dict) -> dict:
    return {
        "id": i["id"],
        "kind": i["kind"],
        "text": sanitize_for_markdown(i.get("text") or "", 300),
        "counterparty": sanitize_for_markdown(i.get("counterparty") or "", 80),
        "due_date": i.get("due_date", ""),
        "status": i.get("status", "open"),
        "evidence": i.get("evidence", []),
        "confidence": (i.get("confidence") or {}).get("level", ""),
        "trust": i.get("trust", "normal"),
        "workstream_id": i.get("workstream_id", ""),
        "first_week": i.get("first_week", ""),
        "last_week": i.get("last_week", ""),
    }


def status(cfg=None, db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    states = {s["source"]: s for s in db.all_sync_states(**kwargs)}
    connectors = []
    for name in SOURCES:
        state = states.get(name, {})
        env_name = {"gmail": "", "github": "GITHUB_TOKEN", "notion": "NOTION_TOKEN"}[name]
        cred = secrets.describe(env_name) if env_name else {"configured": None, "origin": "oauth", "masked": "—"}
        connectors.append({
            "source": name,
            "last_status": state.get("last_status", "never"),
            "last_success_at": state.get("last_success_at", ""),
            "last_error": state.get("last_error", ""),
            "cursor_ts": state.get("cursor_ts", ""),
            "credential": {k: cred.get(k) for k in ("configured", "origin", "masked")},
        })
    analysis_key = secrets.describe("ANTHROPIC_API_KEY")
    return {
        "week": iso_week_of_now(),
        "connectors": connectors,
        "analysis": {k: analysis_key.get(k) for k in ("configured", "origin", "masked")},
        "counts": {
            "workstreams": len(db.list_workstreams(**kwargs)),
            "open_items": len(db.list_items(status="open", **kwargs)),
            "briefings": len(db.list_briefings(**kwargs)),
        },
    }


def briefing(week: str | None = None, db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    target = week or iso_week_of_now()
    row = db.get_briefing_for_week(target, **kwargs)
    if not row:
        available = db.list_briefings(**kwargs)
        return {"week": target, "content": None, "available": [b["week_number"] for b in available]}
    return {"week": target, "content": row["content"], "generated_at": row["generated_at"],
            "available": [b["week_number"] for b in db.list_briefings(**kwargs)]}


def workstreams(db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    weeks = trailing_weeks(clock.now(), 5)
    counts = db.workstream_week_counts(weeks, **kwargs)
    tracks = compute_momentum(db.get_events_for_weeks(weeks, **kwargs), weeks)["tracks"]
    out = []
    for ws in db.list_workstreams(**kwargs):
        week_counts = counts.get(ws["id"], {})
        name_lower = ws["name"].lower()
        trend = next((t["trend"] for t in tracks if t["key"].lower() == name_lower
                      or t["key"].lower().endswith("/" + name_lower)), "")
        out.append({
            "id": ws["id"], "name": ws["name"], "kind": ws["kind"],
            "events_this_week": week_counts.get(weeks[-1], 0),
            "events_window": sum(week_counts.values()),
            "counts": [week_counts.get(w, 0) for w in weeks],
            "trend": trend,
        })
    out.sort(key=lambda w: (-w["events_window"], w["name"]))
    return {"weeks": weeks, "workstreams": out}


def workstream_detail(ws_id: str, db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    ws = next((w for w in db.list_workstreams(**kwargs) if w["id"] == ws_id), None)
    if not ws:
        return {"error": "not_found"}
    events = db.get_events_for_workstream(ws_id, limit=100, **kwargs)
    items = [i for i in db.list_items(**kwargs) if i.get("workstream_id") == ws_id]
    return {"workstream": ws,
            "events": [_event_view(e) for e in events],
            "items": [_item_view(i) for i in items]}


def items(kind: str | None = None, status_filter: str | None = "open", db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    rows = db.list_items(kind=kind, status=status_filter, **kwargs)
    deadlines = {d["id"]: d for d in approaching_deadlines(rows, clock.today())}
    out = []
    for row in rows:
        view = _item_view(row)
        if row["id"] in deadlines:
            view["deadline_state"] = deadlines[row["id"]]["deadline_state"]
            view["days"] = deadlines[row["id"]]["days"]
        out.append(view)
    return {"items": out, "stale": [_item_view(i) for i in
                                    stale_open_items(iso_week_of_now(), 2, **kwargs)]}


def evidence(ids: list[str], db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    return {"events": [_event_view(e) for e in db.get_events_by_ids(ids, **kwargs)]}


def item_history(item_id: str, db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    return {"history": db.get_item_history(item_id, **kwargs)}


def ask(question: str, cfg=None, db_path=None) -> dict:
    return ask_pulse(question, cfg=cfg, db_path=db_path)


def sync_history(db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    return {"sync": db.all_sync_states(**kwargs),
            "suggestions": db.list_link_suggestions(**kwargs)}


def purge(db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    db.purge_all(**kwargs)
    return {"purged": True}


def export(db_path=None) -> dict:
    kwargs = {"db_path": db_path} if db_path else {}
    return db.export_all(**kwargs)



def review(db_path=None) -> dict:
    """A cited attention queue; review decisions remain separate from source facts."""
    kwargs = {"db_path": db_path} if db_path else {}
    rows = items(db_path=db_path)["items"]
    def priority(item):
        if item["trust"] == "suspicious":
            return (0, "Verify source")
        if item.get("deadline_state") == "overdue":
            return (1, "Overdue")
        if item["kind"] == "blocker":
            return (2, "Blocked")
        if item.get("deadline_state"):
            return (3, "Due soon")
        return (4, "Open")
    for item in rows:
        rank, label = priority(item)
        item["priority_rank"], item["priority"] = rank, label
    rows.sort(key=lambda item: (item["priority_rank"], item.get("due_date") or "9999", item["id"]))
    states = {state["source"]: state for state in db.all_sync_states(**kwargs)}
    coverage = [{"source": source, "status": states.get(source, {}).get("last_status", "unknown"),
                 "last_success_at": states.get(source, {}).get("last_success_at", "")}
                for source in SOURCES]
    return {"week": iso_week_of_now(), "items": rows, "coverage": coverage,
            "summary": {"open": len(rows), "verify": sum(i["trust"] == "suspicious" for i in rows),
                        "overdue": sum(i.get("deadline_state") == "overdue" for i in rows)},
            "notice": "Review labels are your triage decisions, not proof that a commitment is complete."}
