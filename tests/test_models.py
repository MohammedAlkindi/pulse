from datetime import datetime, timezone

from agent.store.models import Event, iso_week


class TestIsoWeek:
    def test_mid_year(self):
        assert iso_week(datetime(2026, 7, 29, tzinfo=timezone.utc)) == "2026-W31"

    def test_pads_single_digit_weeks(self):
        assert iso_week(datetime(2026, 1, 7, tzinfo=timezone.utc)) == "2026-W02"

    def test_year_boundary_belongs_to_iso_year(self):
        # 2024-12-30 falls in ISO week 1 of 2025 — the ISO year, not the
        # calendar year, must appear in the key or weeks split in two.
        assert iso_week(datetime(2024, 12, 30, tzinfo=timezone.utc)) == "2025-W01"

    def test_early_january_can_belong_to_prior_iso_year(self):
        assert iso_week(datetime(2027, 1, 1, tzinfo=timezone.utc)) == "2026-W53"


class TestEvent:
    def test_ingested_at_defaults_to_now_iso(self):
        e = Event(
            id="e1", source="github", event_type="commit", title="t",
            metadata={}, occurred_at="2026-07-29T00:00:00+00:00", week_number="2026-W31",
        )
        assert e.ingested_at.endswith("+00:00")
        assert e.week_number == "2026-W31"
