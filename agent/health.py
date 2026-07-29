"""Pre-flight health checks for Pulse.

Critical failures (ANTHROPIC_API_KEY missing, data/ or logs/ not writable) prevent
ingestion from running. Non-critical failures (source tokens, credential files for
enabled sources) produce warnings but allow the run to proceed.
"""

import logging
import os
import tempfile
from pathlib import Path

from agent.config import Config
from agent.paths import DATA_DIR, LOGS_DIR

logger = logging.getLogger(__name__)


def _env_check(env_var: str, *, critical: bool) -> dict:
    status = "ok" if os.getenv(env_var) else "missing"
    return {"name": env_var, "status": status, "_critical": critical}


def _dir_check(directory: Path, label: str, *, critical: bool) -> dict:
    if not directory.exists():
        return {"name": label, "status": "missing", "_critical": critical}
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=True):
            pass
        return {"name": label, "status": "ok", "_critical": critical}
    except OSError:
        return {"name": label, "status": "missing", "_critical": critical}


def _file_check(path: Path, label: str, *, critical: bool) -> dict:
    status = "ok" if path.exists() else "missing"
    return {"name": label, "status": status, "_critical": critical}


def check(cfg: Config, require_analysis: bool = True) -> dict:
    """
    Run all health checks and return a summary dict.

    require_analysis: False for ingestion-only runs (--dry-run), where the
    analysis key is unused and its absence should warn, not block.

    Returns:
        {
            "status": "ok" | "degraded" | "failed",
            "checks": [{"name": str, "status": "ok" | "missing"}, ...]
        }
    """
    raw: list[dict] = []

    # ── critical checks ──────────────────────────────────────────────────────
    api_key_env = cfg.analysis.get("api_key_env", "ANTHROPIC_API_KEY")
    raw.append(_env_check(api_key_env, critical=require_analysis))
    raw.append(_dir_check(DATA_DIR, "data/ writable", critical=True))
    raw.append(_dir_check(LOGS_DIR, "logs/ writable", critical=True))

    # ── non-critical: source tokens and credential files ─────────────────────
    if cfg.source_enabled("github"):
        github_env = cfg.get("sources", "github", "token_env", default="GITHUB_TOKEN")
        raw.append(_env_check(github_env, critical=False))

    if cfg.source_enabled("notion"):
        notion_env = cfg.get("sources", "notion", "token_env", default="NOTION_TOKEN")
        raw.append(_env_check(notion_env, critical=False))

    if cfg.source_enabled("gmail"):
        creds_path = Path(cfg.get(
            "sources", "gmail", "credentials_path",
            default="config/credentials.json",
        ))
        raw.append(_file_check(creds_path, "config/credentials.json", critical=False))

    # ── overall status ───────────────────────────────────────────────────────
    if any(c["_critical"] and c["status"] != "ok" for c in raw):
        status = "failed"
    elif any(not c["_critical"] and c["status"] != "ok" for c in raw):
        status = "degraded"
    else:
        status = "ok"

    checks = [{"name": c["name"], "status": c["status"]} for c in raw]
    return {"status": status, "checks": checks}
