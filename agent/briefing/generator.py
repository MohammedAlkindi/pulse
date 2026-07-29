"""Build the evidence-backed weekly operating review.

Every factual line is rendered through the citation registry, which only
accepts evidence ids present in the run's evidence context (ledger events
plus computed momentum keys). A claim whose citations do not resolve is
dropped and logged — a briefing cannot reference evidence Pulse does not
hold. Interpretive content is labeled as interpretation.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TREND_MARKS = {"rising": "↑", "steady": "→", "falling": "↓", "stalled": "■", "new": "✦"}

_KIND_LABELS = {
    "decision": "Decision",
    "commitment_by_user": "You promised",
    "commitment_by_other": "Promised to you",
    "deadline": "Deadline",
    "blocker": "Blocker",
    "question": "Open question",
}


class Citations:
    """Registry mapping evidence ids to stable [n] markers, with hard
    validation against the evidence context."""

    def __init__(self, event_index: dict[str, dict], momentum: dict | None):
        self._events = event_index or {}
        self._momentum = {
            f"momentum:{t['source']}/{t['key']}": t
            for t in (momentum or {}).get("tracks", [])
        }
        self._order: list[str] = []
        self.dropped = 0

    def _known(self, evidence_id: str) -> bool:
        return evidence_id in self._events or evidence_id in self._momentum

    def ref(self, evidence_ids: list[str]) -> str | None:
        """Return a citation marker for valid ids; None if nothing resolves."""
        valid = [e for e in evidence_ids or [] if self._known(e)]
        if not valid:
            self.dropped += 1
            return None
        numbers = []
        for evidence_id in valid:
            if evidence_id not in self._order:
                self._order.append(evidence_id)
            numbers.append(self._order.index(evidence_id) + 1)
        return "[" + ",".join(str(n) for n in sorted(set(numbers))) + "]"

    def footnotes(self) -> str:
        if not self._order:
            return "_No evidence cited._"
        lines = []
        for i, evidence_id in enumerate(self._order, 1):
            if evidence_id in self._events:
                e = self._events[evidence_id]
                title = (e.get("title") or "(untitled)")[:90]
                url = e.get("canonical_url") or ""
                stamp = (e.get("occurred_at") or "")[:10]
                link = f" — {url}" if url else ""
                lines.append(f"{i}. `{evidence_id}` {e.get('source','')} {stamp}: {title}{link}")
            else:
                t = self._momentum[evidence_id]
                lines.append(
                    f"{i}. `{evidence_id}` computed momentum: {t['trend']} — "
                    f"{t['this_week']} this week vs {t['prior_avg']}/week prior (counts {t['counts']})"
                )
        return "\n".join(lines)


def _cited_lines(entries: list[dict], cite: Citations, empty: str) -> str:
    lines = []
    for entry in entries or []:
        marker = cite.ref(entry.get("evidence", []))
        if marker is None:
            logger.warning("[briefing] dropped uncitable line: %.60s", entry.get("text", ""))
            continue
        lines.append(f"- {entry['text']} {marker}")
    return "\n".join(lines) if lines else empty


def _item_line(item: dict, cite: Citations, extra: str = "") -> str | None:
    marker = cite.ref(item.get("evidence", []))
    if marker is None:
        logger.warning("[briefing] dropped uncitable item: %.60s", item.get("text", ""))
        return None
    label = _KIND_LABELS.get(item["kind"], item["kind"])
    who = f" ({item['counterparty']})" if item.get("counterparty") else ""
    conf = item.get("confidence", {}).get("level", "")
    conf_tag = f" · confidence {conf}" if conf else ""
    # Trust is not confidence: an item can be well-evidenced yet come from a
    # sender trying to manipulate the reader. Say so on the line itself.
    trust = item.get("trust", "normal")
    trust_tag = {
        "suspicious": " · ⚠ UNVERIFIED — source content attempted instruction injection; treat as a claim, not a fact",
        "external": " · claimed by external sender",
    }.get(trust, "")
    return f"- **{label}{who}:** {item['text']}{extra}{conf_tag}{trust_tag} {marker}"


def _item_lines(items: list[dict], cite: Citations, empty: str) -> str:
    lines = [line for item in items if (line := _item_line(item, cite))]
    return "\n".join(lines) if lines else empty


def _deadline_lines(deadlines: list[dict], cite: Citations) -> str:
    lines = []
    for item in deadlines:
        state = ("**OVERDUE by {d} day{s}**".format(d=item["days"], s="" if item["days"] == 1 else "s")
                 if item["deadline_state"] == "overdue"
                 else f"due in {item['days']} day{'' if item['days'] == 1 else 's'}")
        line = _item_line(item, cite, extra=f" — {item['due_date']} ({state})")
        if line:
            lines.append(line)
    return "\n".join(lines) if lines else "_No approaching deadlines in evidence._"


def _momentum_section(momentum: dict | None) -> str:
    tracks = (momentum or {}).get("tracks", [])
    if not tracks:
        return "_Not enough multi-week history to compute momentum yet._"
    rows = "\n".join(
        f"| {_TREND_MARKS.get(t['trend'], '?')} {t['trend']} | {t['source']}/{t['key']} "
        f"| {t['this_week']} | {t['prior_avg']} |"
        for t in tracks[:12]
    )
    return (f"_Computed from {len(momentum['weeks'])} weeks of stored history — not model output._\n\n"
            f"| Trend | Track | This week | Prior avg |\n|-------|-------|-----------|-----------|\n{rows}")


def _source_disclosures(source_status: dict[str, dict] | None) -> list[str]:
    if not source_status:
        return []
    notes = []
    for name, s in sorted(source_status.items()):
        if s.get("status") == "error":
            reason = (s.get("error") or "")[:120]
            notes.append(f"{name} was unavailable this run ({reason}) — its activity is missing from this briefing.")
    return notes


def _activity_table(event_counts: dict[str, dict[str, int]]) -> str:
    gmail = event_counts.get("gmail", {})
    rows = [
        ("Gmail", "Received", gmail.get("email_received", 0)),
        ("Gmail", "Sent", gmail.get("email_sent", 0)),
        ("GitHub", "Events", sum(event_counts.get("github", {}).values())),
        ("Notion", "Pages", sum(event_counts.get("notion", {}).values())),
    ]
    body = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    return f"| Source | Detail | Count |\n|--------|--------|-------|\n{body}"


def generate(
    week: str,
    analysis: dict,
    event_counts: dict[str, dict[str, int]],
    momentum: dict | None = None,
    *,
    changes: dict | None = None,
    open_items: list[dict] | None = None,
    deadlines: list[dict] | None = None,
    stale_items: list[dict] | None = None,
    event_index: dict[str, dict] | None = None,
    source_status: dict[str, dict] | None = None,
) -> str:
    """Assemble the operating review. See module docstring for the rules."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cite = Citations(event_index or {}, momentum)
    changes = changes or {}
    open_items = open_items or []

    commitments = [i for i in open_items
                   if i["kind"] in ("commitment_by_user", "commitment_by_other")]
    risks = [i for i in open_items if i["kind"] in ("blocker", "question")]
    stalled_tracks = [t for t in (momentum or {}).get("tracks", []) if t["trend"] == "stalled"]

    executive = _cited_lines(analysis.get("themes", []), cite,
                             "_Insufficient evidence for an executive summary this week._")
    active = _cited_lines(analysis.get("active_projects", []), cite, "_None evidenced._")

    change_bits = []
    for label, key in (("New decisions", "new_decisions"), ("New commitments", "new_commitments"),
                       ("New risks", "new_risks"), ("Resolved", "resolved")):
        section = _item_lines(changes.get(key, []), cite, "")
        if section:
            change_bits.append(f"**{label}:**\n{section}")
    changes_md = "\n\n".join(change_bits) or "_No material changes recorded this period._"

    decisions_md = _item_lines(changes.get("new_decisions", []), cite,
                               "_No decisions evidenced this week._")
    commitments_md = _item_lines(commitments, cite, "_No open commitments in evidence._")
    deadlines_md = _deadline_lines(deadlines or [], cite)
    risks_md = _item_lines(risks, cite, "_No open risks or blockers in evidence._")
    drifting_md = _cited_lines(analysis.get("drifting", []), cite, "")

    neglected_parts = []
    if stale_items:
        neglected_parts.append(_item_lines(stale_items, cite, ""))
    for t in stalled_tracks:
        marker = cite.ref([f"momentum:{t['source']}/{t['key']}"])
        if marker:
            neglected_parts.append(f"- **Stalled:** {t['source']}/{t['key']} — no activity this week after "
                                   f"averaging {t['prior_avg']}/week {marker}")
    if drifting_md:
        neglected_parts.append(drifting_md)
    neglected_md = "\n".join(p for p in neglected_parts if p) or "_Nothing stalled or neglected in evidence._"

    actions_md = _cited_lines(analysis.get("attention_next_week", []), cite,
                              "_No recommendations — evidence too thin._")

    dq_notes = _source_disclosures(source_status) + list(analysis.get("data_quality_notes", []))
    dq_md = ("\n## Data quality\n" + "\n".join(f"- {n}" for n in dq_notes) + "\n") if dq_notes else ""

    briefing = f"""\
# Weekly Pulse — {week}
_Generated {today} · Every factual claim carries [n] evidence markers that resolve in Sources below. Lines marked Interpretation are analytical judgment, not fact._

## 1 · Executive read
{executive}

**Active:**
{active}

## 2 · Material changes this period
{changes_md}

## 3 · Decisions made
{decisions_md}

## 4 · Open commitments
{commitments_md}

**Approaching deadlines:**
{deadlines_md}

## 5 · Risks & blockers
{risks_md}

## 6 · Workstream momentum
{_momentum_section(momentum)}

## 7 · Neglected or stalled
{neglected_md}

## 8 · Recommended next actions
_Interpretation — Pulse's read of where attention pays off, grounded in the cited evidence:_

{actions_md}

## 9 · Source activity
{_activity_table(event_counts)}
{dq_md}
## Sources
{cite.footnotes()}
"""
    if cite.dropped:
        logger.warning("[briefing] %d line(s) dropped for unresolvable citations.", cite.dropped)
    return briefing
