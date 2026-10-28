import json
from pathlib import Path

from agent import secrets
from scripts import build_site
from scripts.generate_public_sample import generate


def test_snapshot_is_reproducible_synthetic_and_never_consults_credentials(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("public snapshot must not consult credentials")
    monkeypatch.setattr(secrets, "resolve", forbidden)
    first = generate(tmp_path / "first.json")
    second = generate(tmp_path / "second.json")
    assert first == second
    assert first["synthetic"] is True
    ids = {event["id"] for event in first["events"]}
    assert all(set(item["evidence"]) <= ids for item in first["review"]["items"])
    assert first["review"]["items"][0]["trust"] == "suspicious"
    assert "credential" not in json.dumps(first).lower()


def test_public_build_copies_only_declared_public_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "OUTPUT", tmp_path)
    build_site.build()
    names = {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()}
    assert "sample-data.json" in names and "review.js" in names and "workspace.css" in names
    assert not any(name.startswith(("data/", "config/", ".env")) for name in names)
    payload = json.loads((tmp_path / "sample-data.json").read_text())
    assert payload["synthetic"] is True
