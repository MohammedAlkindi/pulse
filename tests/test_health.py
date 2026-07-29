from agent.config import Config
from agent.health import check


def base_cfg():
    return Config({"sources": {}})


class TestHealthCheck:
    def test_missing_analysis_key_fails_normal_runs(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert check(base_cfg())["status"] == "failed"

    def test_missing_analysis_key_only_degrades_dry_runs(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = check(base_cfg(), require_analysis=False)
        assert result["status"] == "degraded"
        assert any(c["name"] == "ANTHROPIC_API_KEY" and c["status"] == "missing"
                   for c in result["checks"])

    def test_all_green_with_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert check(base_cfg())["status"] == "ok"

    def test_enabled_source_without_token_degrades(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        cfg = Config({"sources": {"github": {"enabled": True}}})
        assert check(cfg)["status"] == "degraded"
