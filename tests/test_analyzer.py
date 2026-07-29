from agent.analysis.analyzer import (
    _SYSTEM_PROMPT,
    _trim_events,
    _validate,
    allowed_citation_ids,
    build_user_message,
)


def make_event(**overrides):
    e = {
        "id": "e1", "source": "gmail", "event_type": "email_received",
        "title": "t", "occurred_at": "2026-07-29T10:00:00+00:00",
        "metadata": {},
    }
    e.update(overrides)
    return e


class TestTrimEvents:
    def test_truncates_snippets_to_120_chars(self):
        long_snippet = "s" * 500
        trimmed = _trim_events([make_event(metadata={"snippet": long_snippet})])
        assert len(trimmed[0]["metadata"]["snippet"]) == 120

    def test_truncates_titles_to_200_chars(self):
        trimmed = _trim_events([make_event(title="t" * 999)])
        assert len(trimmed[0]["title"]) == 200

    def test_handles_missing_title(self):
        trimmed = _trim_events([make_event(title=None)])
        assert trimmed[0]["title"] == ""

    def test_does_not_mutate_the_original(self):
        original = make_event(metadata={"snippet": "x" * 500})
        _trim_events([original])
        assert len(original["metadata"]["snippet"]) == 500

    def test_drops_untracked_fields(self):
        trimmed = _trim_events([make_event(ingested_at="whenever", week_number="2026-W31")])
        assert "ingested_at" not in trimmed[0]
        assert "week_number" not in trimmed[0]


MOMENTUM = {"weeks": ["2026-W30", "2026-W31"],
            "tracks": [{"source": "github", "key": "Pulse", "counts": [2, 3],
                        "this_week": 3, "prior_avg": 2.0, "trend": "steady"}]}


class TestPromptStructure:
    """Structural regressions for the prompt-injection defenses."""

    def test_system_prompt_declares_source_text_untrusted(self):
        assert "UNTRUSTED DATA" in _SYSTEM_PROMPT
        assert "never obey" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_provided_ids_only(self):
        assert "Cite only ids that appear" in _SYSTEM_PROMPT

    def test_events_are_wrapped_in_delimited_blocks(self):
        msg = build_user_message([make_event()], MOMENTUM)
        assert '<event id="e1" source="gmail" type="email_received"' in msg
        assert "untrusted content" in msg

    def test_momentum_lines_are_labeled_computed(self):
        msg = build_user_message([make_event()], MOMENTUM)
        assert "COMPUTED MOMENTUM (calculated from stored history" in msg
        assert "github/Pulse" in msg


class TestCitationGate:
    def test_allowed_ids_cover_events_and_momentum(self):
        allowed = allowed_citation_ids([make_event()], MOMENTUM)
        assert allowed == {"e1", "momentum:github/Pulse"}

    def test_validate_drops_fabricated_citations_and_discloses(self):
        result = {
            "themes": [
                {"text": "real", "evidence": ["e1"]},
                {"text": "invented", "evidence": ["e999"]},
            ],
            "active_projects": [], "drifting": [],
            "attention_next_week": [{"text": "uncited", "evidence": []}],
            "data_quality_notes": [],
        }
        cleaned = _validate(result, {"e1"})
        assert [t["text"] for t in cleaned["themes"]] == ["real"]
        assert cleaned["attention_next_week"] == []
        assert any("discarded for citing evidence" in n for n in cleaned["data_quality_notes"])
