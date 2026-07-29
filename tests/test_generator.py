from agent.briefing.generator import generate

ANALYSIS = {
    "themes": ["shipping DashboardX v2"],
    "active_projects": ["DashboardX"],
    "drifting": ["ProofX"],
    "attention_next_week": ["cut the Pulse release"],
    "data_quality_notes": [],
}


class TestGenerate:
    def test_gmail_counts_come_from_event_types(self):
        # Regression: counts used to be looked up under 'gmail_received' /
        # 'gmail_sent' keys that never existed, so briefings always showed 0.
        counts = {
            "gmail": {"email_received": 12, "email_sent": 5},
            "github": {"commit": 7, "pr_opened": 2},
            "notion": {"page_updated": 3},
        }
        briefing = generate("2026-W31", ANALYSIS, counts)
        assert "| Gmail | Received | 12 |" in briefing
        assert "| Gmail | Sent | 5 |" in briefing
        assert "| GitHub | Events | 9 |" in briefing
        assert "| Notion | Pages | 3 |" in briefing

    def test_sections_render_analysis_content(self):
        briefing = generate("2026-W31", ANALYSIS, {})
        assert "# Weekly Pulse — 2026-W31" in briefing
        assert "- shipping DashboardX v2" in briefing
        assert "- ProofX" in briefing
        assert "- cut the Pulse release" in briefing
        assert "Data Quality Notes" not in briefing

    def test_empty_analysis_uses_fallbacks(self):
        empty = {k: [] for k in ANALYSIS}
        briefing = generate("2026-W31", empty, {})
        assert "_None identified._" in briefing

    def test_data_quality_notes_appear_when_present(self):
        analysis = {**ANALYSIS, "data_quality_notes": ["gmail disabled"]}
        briefing = generate("2026-W31", analysis, {})
        assert "## Data Quality Notes" in briefing
        assert "- gmail disabled" in briefing

    def test_momentum_section_renders_computed_tracks(self):
        momentum = {
            "weeks": ["2026-W28", "2026-W29", "2026-W30", "2026-W31"],
            "tracks": [
                {"source": "github", "key": "ProofX", "counts": [4, 3, 5, 0],
                 "this_week": 0, "prior_avg": 4.0, "trend": "stalled"},
                {"source": "gmail", "key": "ucsd.edu", "counts": [1, 1, 2, 4],
                 "this_week": 4, "prior_avg": 1.33, "trend": "rising"},
            ],
        }
        briefing = generate("2026-W31", ANALYSIS, {}, momentum)
        assert "## Momentum" in briefing
        assert "| ■ stalled | github/ProofX | 0 | 4.0 |" in briefing
        assert "| ↑ rising | gmail/ucsd.edu | 4 | 1.33 |" in briefing

    def test_momentum_section_absent_without_tracks(self):
        briefing = generate("2026-W31", ANALYSIS, {}, {"weeks": [], "tracks": []})
        assert "## Momentum" not in briefing
