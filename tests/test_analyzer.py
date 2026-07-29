from agent.analysis.analyzer import _trim_events


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
