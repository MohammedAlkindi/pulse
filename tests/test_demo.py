"""The demo reviews the week its corpus covers, whatever today's date is."""

from agent import clock, paths
from agent.demo import runner
from agent.demo.corpus import ANCHOR
from agent.store.models import iso_week


def test_demo_reviews_the_corpus_week(tmp_path, monkeypatch):
    # Restore the module globals the demo repoints once the test ends.
    for name in ("DB_PATH", "BRIEFING_DRAFT", "MANIFEST_PATH"):
        monkeypatch.setattr(paths, name, getattr(paths, name))
    monkeypatch.setattr(clock, "_pinned", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    runner.use_demo_paths(tmp_path)
    summary = runner.run()

    assert summary["week"] == iso_week(ANCHOR)
    content = (tmp_path / "briefing_draft.md").read_text(encoding="utf-8")
    assert "No events available for analysis." not in content
    assert "_Not enough multi-week history to compute momentum yet._" not in content
