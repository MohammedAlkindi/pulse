"""YAML config loader with typed accessors and env-var resolution."""

import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    def __init__(self, raw: dict) -> None:
        self._raw = raw

    # ── top-level sections ──────────────────────────────────────────────────

    @property
    def sources(self) -> dict:
        return self._raw.get("sources", {})

    @property
    def analysis(self) -> dict:
        return self._raw.get("analysis", {})

    @property
    def briefing(self) -> dict:
        return self._raw.get("briefing", {})

    # ── per-source helpers ──────────────────────────────────────────────────

    def source_enabled(self, name: str) -> bool:
        return self.sources.get(name, {}).get("enabled", False)

    def source_cfg(self, name: str) -> dict:
        return self.sources.get(name, {})

    # ── env var resolution ──────────────────────────────────────────────────

    def env(self, key: str) -> str:
        """Return the env var value or raise clearly."""
        value = os.getenv(key)
        if not value:
            raise EnvironmentError(f"Required environment variable '{key}' is not set.")
        return value

    def analysis_api_key(self) -> str:
        return self.env(self.analysis.get("api_key_env", "ANTHROPIC_API_KEY"))

    def analysis_model(self) -> str:
        return self.analysis.get("model", "claude-sonnet-4-6")

    # ── raw access ─────────────────────────────────────────────────────────

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._raw
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k, default)
        return node


def load_config(path: str | Path) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open() as f:
        raw = yaml.safe_load(f) or {}
    return Config(raw)
