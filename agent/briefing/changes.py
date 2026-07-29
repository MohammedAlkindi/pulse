"""Deterministic material-changes computation between briefing periods."""

from datetime import date, timedelta

from agent.store import db


def material_changes(week: str, db_path=None) -> dict:
    """
    What actually changed this period, computed from the items ledger:
    items first seen this week, and items resolved this week (from history).
    """
    kwargs = {"db_path": db_path} if db_path else {}
    all_items = db.list_items(**kwargs)

    new_this_week = [i for i in all_items if i["first_week"] == week]
    resolved_ids = set()
    for item in all_items:
        for entry in db.get_item_history(item["id"], **kwargs):
            if entry["change"] == "status:resolved" and entry["week"] == week:
                resolved_ids.add(item["id"])
    resolved = [i for i in all_items if i["id"] in resolved_ids]

    return {
        "new_decisions": [i for i in new_this_week if i["kind"] == "decision"],
        "new_commitments": [i for i in new_this_week
                            if i["kind"] in ("commitment_by_user", "commitment_by_other")],
        "new_risks": [i for i in new_this_week if i["kind"] in ("blocker", "question")],
        "resolved": resolved,
    }


def approaching_deadlines(items: list[dict], today: date, horizon_days: int = 7) -> list[dict]:
    """Open items due within the horizon, or already overdue — annotated."""
    out = []
    for item in items:
        if item.get("status") != "open" or not item.get("due_date"):
            continue
        try:
            due = date.fromisoformat(item["due_date"])
        except ValueError:
            continue
        if due < today:
            out.append({**item, "deadline_state": "overdue", "days": (today - due).days})
        elif due <= today + timedelta(days=horizon_days):
            out.append({**item, "deadline_state": "due_soon", "days": (due - today).days})
    out.sort(key=lambda i: i["due_date"])
    return out
