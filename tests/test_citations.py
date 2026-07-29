from agent.analysis.citations import derive_confidence, validate_citations

ALLOWED = {"gmail:1", "github:2", "notion:3", "momentum:github/Pulse"}


class TestValidateCitations:
    def test_fully_cited_entries_pass(self):
        entries = [{"text": "a", "evidence": ["gmail:1", "github:2"]}]
        valid, rejected = validate_citations(entries, ALLOWED)
        assert valid == entries and rejected == []

    def test_fabricated_evidence_is_rejected_not_repaired(self):
        entries = [{"text": "a", "evidence": ["gmail:1", "gmail:FAKE"]}]
        valid, rejected = validate_citations(entries, ALLOWED)
        assert valid == [] and rejected == entries

    def test_uncited_entries_are_rejected(self):
        for evidence in ([], None, "gmail:1", [42]):
            valid, rejected = validate_citations([{"text": "a", "evidence": evidence}], ALLOWED)
            assert valid == [], f"evidence={evidence!r} should not validate"

    def test_mixed_batch_splits_correctly(self):
        entries = [
            {"text": "ok", "evidence": ["notion:3"]},
            {"text": "bad", "evidence": ["nope:0"]},
        ]
        valid, rejected = validate_citations(entries, ALLOWED)
        assert [e["text"] for e in valid] == ["ok"]
        assert [e["text"] for e in rejected] == ["bad"]


class TestDeriveConfidence:
    def ev(self, source, week):
        return {"source": source, "week_number": week}

    def test_multi_source_corroboration_is_high(self):
        c = derive_confidence([self.ev("gmail", "2026-W31"), self.ev("github", "2026-W31")], "2026-W31")
        assert c["level"] == "high"
        assert c["basis"]["distinct_sources"] == ["github", "gmail"]

    def test_two_events_same_source_is_high(self):
        c = derive_confidence([self.ev("gmail", "2026-W30"), self.ev("gmail", "2026-W31")], "2026-W31")
        assert c["level"] == "high"

    def test_single_recent_event_is_medium(self):
        assert derive_confidence([self.ev("gmail", "2026-W31")], "2026-W31")["level"] == "medium"
        assert derive_confidence([self.ev("gmail", "2026-W30")], "2026-W31")["level"] == "medium"

    def test_single_old_event_is_low(self):
        assert derive_confidence([self.ev("gmail", "2026-W25")], "2026-W31")["level"] == "low"

    def test_no_evidence_is_low(self):
        assert derive_confidence([], "2026-W31")["level"] == "low"

    def test_basis_is_reported_not_asserted(self):
        c = derive_confidence([self.ev("gmail", "2026-W29")], "2026-W31")
        assert c["basis"]["most_recent_weeks_ago"] == 2
        assert c["basis"]["evidence_count"] == 1
