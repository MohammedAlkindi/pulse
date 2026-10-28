"""Export only the declared synthetic corpus, never a runtime ledger or config."""
import json
import hashlib
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def generate(output=None):
    from agent import clock, paths
    from agent.demo import runner
    from agent.demo.corpus import ANCHOR
    from agent.store import db
    from agent.web import api
    previous = (paths.DB_PATH, paths.BRIEFING_DRAFT, paths.MANIFEST_PATH, clock._pinned)
    try:
        with tempfile.TemporaryDirectory(prefix="pulse-public-synthetic-") as temp:
            runner.use_demo_paths(Path(temp))
            from agent.analysis.extract import extract_candidates
            from agent.analysis.items_sync import sync_items, stale_open_items
            from agent.analysis.momentum import trailing_weeks, compute_momentum
            from agent.graph.workstreams import resolve_events
            from agent.briefing.changes import material_changes, approaching_deadlines
            from agent.briefing.generator import generate as briefing_text
            from agent.store.models import Briefing, iso_week
            runner.seed(reset=False)
            clock.pin(ANCHOR)
            weeks = trailing_weeks(ANCHOR, 6)
            week = iso_week(ANCHOR)
            resolve_events(db.get_unassigned_events(weeks), cfg=runner.DEMO_CONFIG)
            window = db.get_events_for_weeks_full(weeks)
            index = {event["id"]: event for event in window}
            candidates = extract_candidates(window, known_domains={"example.com"})
            for candidate in candidates:
                candidate["workstream_id"] = index.get(candidate["evidence"][0], {}).get("workstream_id", "")
            sync_items(candidates, week, event_index=index)
            momentum_weeks = trailing_weeks(ANCHOR, 5)
            momentum = compute_momentum(db.get_events_for_weeks(momentum_weeks), momentum_weeks)
            open_items = db.list_items(status="open")
            empty_analysis = {"themes": [], "active_projects": [], "drifting": [], "attention_next_week": [], "data_quality_notes": []}
            content = briefing_text(week, empty_analysis, db.count_events_by_type_for_week(week), momentum,
                                   changes=material_changes(week), open_items=open_items,
                                   deadlines=approaching_deadlines(open_items, ANCHOR.date()),
                                   stale_items=stale_open_items(week, 2), event_index=index)
            content = re.sub(r"(?m)^_Generated [^\n]*$", "_Synthetic reference: 2026-W31. Every factual claim links to invented source records below._", content)
            db.insert_briefing(Briefing(id="public-synthetic", week_number=week, content=content, generated_at=ANCHOR.isoformat()))
            rows = window
            payload = {"synthetic": True, "reference_date": ANCHOR.isoformat(), "review": api.review(),
                       "items": api.items(), "workstreams": api.workstreams(),
                       "events": api.evidence([row["id"] for row in rows])["events"],
                       "briefing": api.briefing()}
            payload["briefing"]["generated_at"] = ANCHOR.isoformat()
            for collection in (payload["review"]["items"], payload["items"]["items"], payload["items"]["stale"]):
                for item in collection:
                    identity = item["kind"] + item["text"] + ",".join(sorted(item["evidence"]))
                    item["id"] = "sample-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            for collection in (payload["review"]["items"], payload["items"]["items"], payload["items"]["stale"]):
                collection.sort(key=lambda item: (item.get("priority_rank", 10), item.get("due_date") or "9999", item["id"]))
            target = Path(output) if output else ROOT / "site/sample-data.json"
            target.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            if output is None:
                (ROOT / "site/sample.md").write_text(content, encoding="utf-8")
            return payload
    finally:
        paths.DB_PATH, paths.BRIEFING_DRAFT, paths.MANIFEST_PATH, pinned = previous
        clock.pin(pinned)


if __name__ == "__main__":
    generate()
