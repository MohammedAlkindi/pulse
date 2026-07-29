from datetime import datetime, timezone

from agent.analysis.momentum import (
    classify,
    compute_momentum,
    momentum_summary_for_prompt,
    track_key,
    trailing_weeks,
)


class TestTrailingWeeks:
    def test_returns_n_weeks_ending_with_current(self):
        weeks = trailing_weeks(datetime(2026, 7, 29, tzinfo=timezone.utc), 5)
        assert weeks == ["2026-W27", "2026-W28", "2026-W29", "2026-W30", "2026-W31"]

    def test_crosses_year_boundaries(self):
        weeks = trailing_weeks(datetime(2027, 1, 8, tzinfo=timezone.utc), 3)
        assert weeks == ["2026-W52", "2026-W53", "2027-W01"]


class TestTrackKey:
    def test_github_uses_repo(self):
        assert track_key({"source": "github", "metadata": {"repo": "Pulse"}}) == "Pulse"

    def test_notion_uses_title_with_page_id_fallback(self):
        assert track_key({"source": "notion", "title": "Roadmap", "metadata": {}}) == "Roadmap"
        assert track_key({"source": "notion", "title": "  ", "metadata": {"page_id": "p1"}}) == "p1"

    def test_gmail_uses_sender_domain(self):
        e = {"source": "gmail", "metadata": {"sender": "UC San Diego <admissions@ucsd.edu>"}}
        assert track_key(e) == "ucsd.edu"

    def test_unknown_source_or_missing_key_is_none(self):
        assert track_key({"source": "carrier-pigeon", "metadata": {}}) is None
        assert track_key({"source": "github", "metadata": {}}) is None


class TestClassify:
    def test_new_track(self):
        assert classify(3, [0, 0, 0, 0]) == "new"

    def test_stalled_track(self):
        assert classify(0, [4, 3, 5, 2]) == "stalled"

    def test_rising_track(self):
        assert classify(6, [2, 2, 2, 2]) == "rising"

    def test_falling_track(self):
        assert classify(1, [4, 4, 4, 4]) == "falling"

    def test_steady_track(self):
        assert classify(3, [3, 2, 4, 3]) == "steady"

    def test_no_history_no_activity_is_steady(self):
        assert classify(0, [0, 0, 0, 0]) == "steady"


def ev(week, source="github", repo=None, title="", sender=""):
    meta = {}
    if repo:
        meta["repo"] = repo
    if sender:
        meta["sender"] = sender
    return {"source": source, "title": title, "metadata": meta, "week_number": week}


WEEKS = ["2026-W28", "2026-W29", "2026-W30", "2026-W31"]


class TestComputeMomentum:
    def test_counts_per_track_per_week(self):
        events = [
            ev("2026-W28", repo="Pulse"), ev("2026-W29", repo="Pulse"),
            ev("2026-W30", repo="Pulse"), ev("2026-W31", repo="Pulse"), ev("2026-W31", repo="Pulse"),
        ]
        m = compute_momentum(events, WEEKS)
        assert len(m["tracks"]) == 1
        t = m["tracks"][0]
        assert t["key"] == "Pulse"
        assert t["counts"] == [1, 1, 1, 2]
        assert t["this_week"] == 2
        assert t["prior_avg"] == 1.0

    def test_filters_noise_tracks(self):
        m = compute_momentum([ev("2026-W31", repo="one-off")], WEEKS)
        assert m["tracks"] == []

    def test_ignores_events_outside_the_window(self):
        events = [ev("2020-W01", repo="Ancient"), ev("2020-W02", repo="Ancient")]
        assert compute_momentum(events, WEEKS)["tracks"] == []

    def test_stalled_and_falling_sort_before_rising_and_steady(self):
        events = (
            [ev(w, repo="stalled-repo") for w in WEEKS[:-1]] +
            [ev("2026-W31", repo="rising-repo"), ev("2026-W31", repo="rising-repo"),
             ev("2026-W28", repo="rising-repo")] +
            [ev(w, repo="steady-repo") for w in WEEKS]
        )
        m = compute_momentum(events, WEEKS)
        trends = [t["trend"] for t in m["tracks"]]
        assert trends[0] == "stalled"
        assert trends.index("rising") < trends.index("steady")

    def test_mixed_sources_stay_separate_tracks(self):
        events = [
            ev("2026-W30", repo="Pulse"), ev("2026-W31", repo="Pulse"),
            ev("2026-W30", source="gmail", sender="a@ucsd.edu"),
            ev("2026-W31", source="gmail", sender="b@ucsd.edu"),
        ]
        m = compute_momentum(events, WEEKS)
        keys = {(t["source"], t["key"]) for t in m["tracks"]}
        assert keys == {("github", "Pulse"), ("gmail", "ucsd.edu")}


class TestPromptSummary:
    def test_empty_history_says_so(self):
        assert "first weeks" in momentum_summary_for_prompt({"weeks": WEEKS, "tracks": []})

    def test_lines_carry_trend_and_counts(self):
        events = [ev(w, repo="Pulse") for w in WEEKS]
        s = momentum_summary_for_prompt(compute_momentum(events, WEEKS))
        assert "STEADY: github/Pulse" in s
        assert "[1, 1, 1, 1]" in s
