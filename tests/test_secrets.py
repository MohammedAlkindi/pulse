from agent import secrets
from agent.config import Config


class TestMask:
    def test_never_reveals_more_than_a_tail(self):
        masked = secrets.mask("sk-ant-api03-supersecretvalue-1234")
        assert "supersecret" not in masked
        assert masked.endswith("1234")

    def test_short_secrets_are_fully_hidden(self):
        assert secrets.mask("abc123") == "••••••"

    def test_missing_secret(self):
        assert secrets.mask(None) == "(not set)"
        assert secrets.mask("") == "(not set)"


class TestRedact:
    # Token-shaped fixtures are assembled at runtime so no credential-looking
    # literal is ever committed to the repository (secret scanners flag them,
    # rightly, and a fixture is indistinguishable from the real thing).
    def test_scrubs_provider_token_shapes(self):
        body = "abcdefghijklmnopqrst1234"
        samples = [
            f"failed with key {'sk-' + 'ant-api03-'}{body}",
            f"Authorization: token {'gh' + 'p_'}{body}",
            f"notion said {'ntn' + '_'}{body}",
            f"google returned {'ya' + '29.'}a0AfB_byC{body}",
        ]
        for text in samples:
            assert "[redacted]" in secrets.redact(text), text

    def test_scrubs_header_style_assignments(self):
        assert "[redacted]" in secrets.redact("Authorization: Bearer abc.def.ghi")
        assert "[redacted]" in secrets.redact('api_key=hunter2hunter2')

    def test_scrubs_known_values_verbatim(self):
        text = "connection failed for my-literal-secret-value"
        assert "my-literal-secret-value" not in secrets.redact(text, extra=["my-literal-secret-value"])

    def test_leaves_ordinary_text_alone(self):
        assert secrets.redact("gmail ingestion failed: connection reset") == \
            "gmail ingestion failed: connection reset"

    def test_handles_empty_input(self):
        assert secrets.redact("") == ""


class TestResolution:
    def test_environment_wins(self, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: "from-keychain")
        assert secrets.resolve("X", env={"X": "from-env"}) == "from-env"

    def test_falls_back_to_keychain(self, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: "from-keychain")
        assert secrets.resolve("X", env={}) == "from-keychain"

    def test_missing_everywhere(self, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: None)
        assert secrets.resolve("X", env={}) is None

    def test_describe_reports_origin_without_the_value(self, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: None)
        described = secrets.describe("X", env={"X": "sk-ant-supersecretvalue"})
        assert described["configured"] is True
        assert described["origin"] == "environment"
        assert "supersecret" not in described["masked"]

    def test_config_env_uses_the_resolver(self, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: "keychain-value")
        monkeypatch.delenv("PULSE_TEST_ONLY", raising=False)
        assert Config({}).env("PULSE_TEST_ONLY") == "keychain-value"

    def test_config_env_error_mentions_both_options(self, monkeypatch):
        monkeypatch.setattr(secrets, "keyring_get", lambda name: None)
        monkeypatch.delenv("PULSE_TEST_ONLY", raising=False)
        try:
            Config({}).env("PULSE_TEST_ONLY")
        except EnvironmentError as exc:
            assert "keychain" in str(exc)
        else:
            raise AssertionError("should have raised")


class TestNoSecretsInStoredData:
    def test_sync_errors_are_redacted_before_storage(self, tmp_path, monkeypatch):
        from functools import partial
        from agent import paths, scheduler
        from agent.store import db

        path = tmp_path / "s.db"
        monkeypatch.setattr(paths, "DB_PATH", path)
        db.init_db(path)
        monkeypatch.setattr(scheduler, "get_sync_state", partial(db.get_sync_state, db_path=path))
        monkeypatch.setattr(scheduler, "set_sync_state", partial(db.set_sync_state, db_path=path))
        monkeypatch.setattr(scheduler, "upsert_events", partial(db.upsert_events, db_path=path))

        def leaky(cfg, since):
            raise RuntimeError("401 for token ghp_abcdefghijklmnopqrst1234")

        result = scheduler._ingest_source("github", Config({}), fetcher=leaky)
        assert "ghp_" not in result["error"]
        assert "ghp_" not in db.get_sync_state("github", path)["last_error"]
