import json

import pytest

from agent import paths, secrets
from agent.analysis.extract import extract_candidates
from agent.analysis.items_sync import sync_items
from agent.analysis.momentum import trailing_weeks
from agent.demo.corpus import ANCHOR, build_corpus
from agent.demo.runner import DEMO_CONFIG
from agent.graph.workstreams import resolve_events
from agent.store import db
from agent.store.models import Briefing, iso_week
from agent.web import api
from agent.web.server import _SECURITY_HEADERS, serve

WEEK = iso_week(ANCHOR)


@pytest.fixture
def corpus_db(tmp_path, monkeypatch):
    path = tmp_path / "web.db"
    monkeypatch.setattr(paths, "DB_PATH", path)
    db.init_db(path)
    db.upsert_events(build_corpus(), path)
    weeks = trailing_weeks(ANCHOR, 6)
    resolve_events(db.get_unassigned_events(weeks, path), cfg=DEMO_CONFIG, db_path=path)
    window = db.get_events_for_weeks_full(weeks, path)
    sync_items(extract_candidates(window), WEEK,
               event_index={e["id"]: e for e in window}, db_path=path)
    return path


class TestStatus:
    def test_reports_connectors_and_counts(self, corpus_db, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: None)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        s = api.status(db_path=corpus_db)
        assert {c["source"] for c in s["connectors"]} == {"gmail", "github", "notion"}
        assert s["counts"]["workstreams"] > 0

    def test_never_returns_a_secret_value(self, corpus_db, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecretvalue1234567890")
        monkeypatch.setattr(secrets, "keyring_get", lambda name: None)
        blob = json.dumps(api.status(db_path=corpus_db))
        assert "supersecretvalue" not in blob
        assert "ghp_supersecret" not in blob


class TestBriefing:
    def test_missing_week_lists_alternatives(self, corpus_db):
        db.insert_briefing(Briefing(id="b1", week_number="2026-W29", content="# old"), corpus_db)
        data = api.briefing("2099-W01", db_path=corpus_db)
        assert data["content"] is None
        assert "2026-W29" in data["available"]

    def test_returns_stored_content(self, corpus_db):
        db.insert_briefing(Briefing(id="b2", week_number=WEEK, content="# hello"), corpus_db)
        assert api.briefing(WEEK, db_path=corpus_db)["content"] == "# hello"


class TestWorkstreamsView:
    def test_lists_with_activity_and_trend(self, corpus_db):
        data = api.workstreams(db_path=corpus_db)
        assert data["workstreams"]
        assert all("events_window" in w for w in data["workstreams"])

    def test_detail_returns_events_and_items(self, corpus_db):
        ws_id = api.workstreams(db_path=corpus_db)["workstreams"][0]["id"]
        detail = api.workstream_detail(ws_id, db_path=corpus_db)
        assert detail["workstream"]["id"] == ws_id
        assert isinstance(detail["events"], list)

    def test_unknown_workstream(self, corpus_db):
        assert api.workstream_detail("nope", db_path=corpus_db)["error"] == "not_found"


class TestItemsView:
    def test_open_items_carry_evidence_and_trust(self, corpus_db):
        data = api.items(db_path=corpus_db)
        assert data["items"]
        for item in data["items"]:
            assert item["evidence"]
            assert item["trust"] in ("normal", "external", "suspicious")

    def test_hostile_items_are_flagged_for_the_ui(self, corpus_db):
        flagged = [i for i in api.items(db_path=corpus_db)["items"] if i["trust"] == "suspicious"]
        assert flagged, "injection-sourced items must reach the UI marked suspicious"

    def test_rendered_text_is_sanitized(self, corpus_db):
        for item in api.items(db_path=corpus_db)["items"]:
            assert "</event>" not in item["text"]
            assert "<script" not in item["text"].lower()


class TestEvidenceDrawer:
    def test_resolves_ids_to_source_records(self, corpus_db):
        item = api.items(db_path=corpus_db)["items"][0]
        data = api.evidence(item["evidence"], db_path=corpus_db)
        assert data["events"]
        assert data["events"][0]["id"] in item["evidence"]

    def test_unknown_ids_return_nothing_rather_than_guessing(self, corpus_db):
        assert api.evidence(["github:nonexistent"], db_path=corpus_db)["events"] == []


class TestRetentionEndpoints:
    def test_export_then_purge(self, corpus_db):
        assert api.export(db_path=corpus_db)["events"]
        api.purge(db_path=corpus_db)
        assert api.export(db_path=corpus_db)["events"] == []


class TestServerSafety:
    def test_refuses_non_local_bind(self):
        with pytest.raises(ValueError):
            serve(DEMO_CONFIG, host="0.0.0.0")

    def test_security_headers_are_strict(self):
        csp = _SECURITY_HEADERS["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
        assert _SECURITY_HEADERS["X-Frame-Options"] == "DENY"
