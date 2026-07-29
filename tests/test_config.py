import pytest

from agent.config import Config, load_config


def write_config(tmp_path, text):
    p = tmp_path / "pulse_config.yaml"
    p.write_text(text)
    return p


class TestLoadConfig:
    def test_missing_file_raises_clearly(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_empty_file_yields_empty_config(self, tmp_path):
        cfg = load_config(write_config(tmp_path, ""))
        assert cfg.sources == {}
        assert cfg.source_enabled("gmail") is False


class TestAccessors:
    def test_source_enabled(self, tmp_path):
        cfg = load_config(write_config(tmp_path, "sources:\n  github:\n    enabled: true\n"))
        assert cfg.source_enabled("github") is True
        assert cfg.source_enabled("gmail") is False
        assert cfg.source_cfg("github") == {"enabled": True}

    def test_nested_get_with_default(self):
        cfg = Config({"a": {"b": {"c": 1}}})
        assert cfg.get("a", "b", "c") == 1
        assert cfg.get("a", "missing", default="fallback") == "fallback"

    def test_env_raises_when_unset(self, monkeypatch):
        monkeypatch.delenv("PULSE_TEST_KEY", raising=False)
        with pytest.raises(EnvironmentError):
            Config({}).env("PULSE_TEST_KEY")

    def test_env_returns_value(self, monkeypatch):
        monkeypatch.setenv("PULSE_TEST_KEY", "secret")
        assert Config({}).env("PULSE_TEST_KEY") == "secret"

    def test_analysis_key_env_is_configurable(self, monkeypatch):
        monkeypatch.setenv("OTHER_KEY", "k")
        cfg = Config({"analysis": {"api_key_env": "OTHER_KEY"}})
        assert cfg.analysis_api_key() == "k"

    def test_analysis_model_defaults_to_opus_5(self):
        assert Config({}).analysis_model() == "claude-opus-5"
        assert Config({"analysis": {"model": "claude-haiku-4-5"}}).analysis_model() == "claude-haiku-4-5"
