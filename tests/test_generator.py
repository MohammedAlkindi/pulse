from agent.briefing.generator import Citations, generate

EVENT_INDEX = {
    "gmail:1": {"id": "gmail:1", "source": "gmail", "title": "Re: Q3 numbers",
                "canonical_url": "https://mail.google.com/mail/u/0/#all/1",
                "occurred_at": "2026-07-28T09:00:00+00:00"},
    "github:2": {"id": "github:2", "source": "github", "title": "fix: sync cursors",
                 "canonical_url": "https://github.com/u/pulse/commit/abc",
                 "occurred_at": "2026-07-29T10:00:00+00:00"},
}

MOMENTUM = {
    "weeks": ["2026-W28", "2026-W29", "2026-W30", "2026-W31"],
    "tracks": [
        {"source": "github", "key": "ProofX", "counts": [4, 3, 5, 0],
         "this_week": 0, "prior_avg": 4.0, "trend": "stalled"},
        {"source": "github", "key": "Pulse", "counts": [1, 1, 2, 4],
         "this_week": 4, "prior_avg": 1.33, "trend": "rising"},
    ],
}

ANALYSIS = {
    "themes": [{"text": "Sync work dominated the week", "evidence": ["github:2"]}],
    "active_projects": [{"text": "Pulse", "evidence": ["github:2", "momentum:github/Pulse"]}],
    "drifting": [{"text": "ProofX has gone quiet", "evidence": ["momentum:github/ProofX"]}],
    "attention_next_week": [{"text": "Close the Q3 numbers thread", "evidence": ["gmail:1"]}],
    "data_quality_notes": [],
}

COMMITMENT = {
    "id": "it1", "kind": "commitment_by_user", "text": "Send Sarah the Q3 numbers",
    "counterparty": "Sarah", "due_date": "2026-08-01", "status": "open",
    "evidence": ["gmail:1"], "confidence": {"level": "medium", "basis": {}},
    "first_week": "2026-W31", "last_week": "2026-W31",
}


def gen(**overrides):
    kwargs = dict(momentum=MOMENTUM, event_index=EVENT_INDEX)
    kwargs.update(overrides)
    return generate("2026-W31", ANALYSIS, {}, kwargs.pop("momentum"), **kwargs)


class TestCitations:
    def test_markers_resolve_in_sources(self):
        briefing = gen()
        assert "Sync work dominated the week [1]" in briefing
        assert "1. `github:2` github 2026-07-29: fix: sync cursors — https://github.com/u/pulse/commit/abc" in briefing

    def test_momentum_citations_resolve_to_computed_lines(self):
        briefing = gen()
        assert "ProofX has gone quiet" in briefing
        assert "computed momentum: stalled — 0 this week vs 4.0/week prior" in briefing

    def test_fabricated_citation_drops_the_claim(self):
        poisoned = {**ANALYSIS,
                    "themes": [{"text": "Fabricated triumph", "evidence": ["github:NOPE"]}]}
        briefing = generate("2026-W31", poisoned, {}, MOMENTUM, event_index=EVENT_INDEX)
        assert "Fabricated triumph" not in briefing
        assert "Insufficient evidence for an executive summary" in briefing

    def test_uncited_claim_is_dropped(self):
        poisoned = {**ANALYSIS, "themes": [{"text": "Trust me", "evidence": []}]}
        briefing = generate("2026-W31", poisoned, {}, MOMENTUM, event_index=EVENT_INDEX)
        assert "Trust me" not in briefing

    def test_citation_numbers_follow_first_appearance(self):
        cite = Citations(EVENT_INDEX, MOMENTUM)
        assert cite.ref(["github:2"]) == "[1]"
        assert cite.ref(["gmail:1"]) == "[2]"
        assert cite.ref(["github:2", "gmail:1"]) == "[1,2]"


class TestItemsRendering:
    def test_commitment_renders_with_label_counterparty_and_confidence(self):
        briefing = gen(open_items=[COMMITMENT])
        assert "**You promised (Sarah):** Send Sarah the Q3 numbers · confidence medium" in briefing

    def test_overdue_deadline_is_loud(self):
        deadline = {**COMMITMENT, "deadline_state": "overdue", "days": 3}
        briefing = gen(deadlines=[deadline])
        assert "OVERDUE by 3 days" in briefing
        assert "2026-08-01" in briefing

    def test_due_soon_deadline_shows_countdown(self):
        deadline = {**COMMITMENT, "deadline_state": "due_soon", "days": 2}
        briefing = gen(deadlines=[deadline])
        assert "due in 2 days" in briefing

    def test_item_with_unknown_evidence_is_dropped(self):
        bogus = {**COMMITMENT, "evidence": ["gmail:GHOST"]}
        briefing = gen(open_items=[bogus])
        assert "Send Sarah the Q3 numbers" not in briefing
        assert "_No open commitments in evidence._" in briefing

    def test_material_changes_group_by_type(self):
        decision = {**COMMITMENT, "id": "d1", "kind": "decision",
                    "text": "Adopt SQLite for the ledger", "counterparty": ""}
        briefing = gen(changes={"new_decisions": [decision], "new_commitments": [COMMITMENT],
                                "new_risks": [], "resolved": []})
        assert "**New decisions:**" in briefing
        assert "**Decision:** Adopt SQLite for the ledger" in briefing


class TestSections:
    def test_stalled_momentum_lands_in_neglected(self):
        briefing = gen()
        assert "**Stalled:** github/ProofX — no activity this week after averaging 4.0/week" in briefing

    def test_recommendations_are_labeled_interpretation(self):
        briefing = gen()
        assert "_Interpretation — Pulse's read" in briefing
        assert "Close the Q3 numbers thread" in briefing

    def test_gmail_counts_come_from_event_types(self):
        counts = {"gmail": {"email_received": 12, "email_sent": 5},
                  "github": {"commit": 7, "pr_opened": 2}, "notion": {"page_updated": 3}}
        briefing = generate("2026-W31", ANALYSIS, counts, MOMENTUM, event_index=EVENT_INDEX)
        assert "| Gmail | Received | 12 |" in briefing
        assert "| Gmail | Sent | 5 |" in briefing
        assert "| GitHub | Events | 9 |" in briefing

    def test_source_failure_is_disclosed(self):
        briefing = gen(source_status={"gmail": {"status": "error", "error": "token expired"}})
        assert "gmail was unavailable this run (token expired)" in briefing

    def test_empty_week_says_so_instead_of_inventing(self):
        empty_analysis = {"themes": [], "active_projects": [], "drifting": [],
                          "attention_next_week": [], "data_quality_notes": []}
        briefing = generate("2026-W31", empty_analysis, {}, None, event_index={})
        assert "Insufficient evidence for an executive summary" in briefing
        assert "_No open commitments in evidence._" in briefing
        assert "_No decisions evidenced this week._" in briefing
        assert "_No recommendations — evidence too thin._" in briefing
        assert "Not enough multi-week history" in briefing
        assert "_No evidence cited._" in briefing
