"""Pre-flight health checks and live connector tests for Pulse.

Two distinct questions:
  check()          — is the local environment usable? (cheap, no network)
  test_connector() — will this credential actually work? (one live call)

Critical failures (missing analysis key when analysis will run, data/ or
logs/ not writable) prevent a run. Non-critical failures (source tokens,
credential files for enabled sources) warn and continue, because partial
evidence still produces a useful briefing.
"""

import logging
import tempfile
from pathlib import Path

from agent.config import Config
from agent.paths import DATA_DIR, LOGS_DIR
from agent.secrets import redact, resolve

logger = logging.getLogger(__name__)


def _env_check(env_var: str, *, critical: bool) -> dict:
    status = "ok" if resolve(env_var) else "missing"
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
    """
    raw: list[dict] = []

    api_key_env = cfg.analysis.get("api_key_env", "ANTHROPIC_API_KEY")
    raw.append(_env_check(api_key_env, critical=require_analysis))
    raw.append(_dir_check(DATA_DIR, "data/ writable", critical=True))
    raw.append(_dir_check(LOGS_DIR, "logs/ writable", critical=True))

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

    if any(c["_critical"] and c["status"] != "ok" for c in raw):
        status = "failed"
    elif any(not c["_critical"] and c["status"] != "ok" for c in raw):
        status = "degraded"
    else:
        status = "ok"

    checks = [{"name": c["name"], "status": c["status"]} for c in raw]
    return {"status": status, "checks": checks}


# ── live connector tests ────────────────────────────────────────────────────

def test_github(cfg: Config) -> dict:
    token_env = cfg.get("sources", "github", "token_env", default="GITHUB_TOKEN")
    token = resolve(token_env)
    if not token:
        return {"source": "github", "ok": False, "detail": f"{token_env} not set"}
    try:
        import requests
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return {"source": "github", "ok": True,
                    "detail": f"authenticated as {resp.json().get('login', '?')}"}
        return {"source": "github", "ok": False,
                "detail": f"HTTP {resp.status_code} — token may be invalid or expired"}
    except Exception as exc:
        return {"source": "github", "ok": False, "detail": redact(str(exc))[:200]}


def test_notion(cfg: Config) -> dict:
    token_env = cfg.get("sources", "notion", "token_env", default="NOTION_TOKEN")
    token = resolve(token_env)
    if not token:
        return {"source": "notion", "ok": False, "detail": f"{token_env} not set"}
    try:
        import requests
        resp = requests.get(
            "https://api.notion.com/v1/users/me",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"},
            timeout=15,
        )
        if resp.status_code == 200:
            return {"source": "notion", "ok": True, "detail": "integration token accepted"}
        return {"source": "notion", "ok": False,
                "detail": f"HTTP {resp.status_code} — token may be invalid or lack access"}
    except Exception as exc:
        return {"source": "notion", "ok": False, "detail": redact(str(exc))[:200]}


def test_gmail(cfg: Config) -> dict:
    creds = Path(cfg.get("sources", "gmail", "credentials_path", default="config/credentials.json"))
    token = Path(cfg.get("sources", "gmail", "token_path", default="config/token.json"))
    if not creds.exists():
        return {"source": "gmail", "ok": False, "detail": f"{creds} missing — download OAuth client JSON"}
    if not token.exists():
        return {"source": "gmail", "ok": False,
                "detail": "not yet authorised — run a sync once to complete the OAuth flow"}
    try:
        from agent.sources.gmail import _build_service
        service = _build_service(str(creds), str(token))
        profile = service.users().getProfile(userId="me").execute()
        return {"source": "gmail", "ok": True,
                "detail": f"authorised for {profile.get('emailAddress', '?')}"}
    except Exception as exc:
        return {"source": "gmail", "ok": False, "detail": redact(str(exc))[:200]}


def test_anthropic(cfg: Config) -> dict:
    key_env = cfg.analysis.get("api_key_env", "ANTHROPIC_API_KEY")
    key = resolve(key_env)
    if not key:
        return {"source": "anthropic", "ok": False,
                "detail": f"{key_env} not set — Pulse still runs, without model analysis"}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        client.messages.create(model=cfg.analysis_model(), max_tokens=1,
                               messages=[{"role": "user", "content": "ping"}])
        return {"source": "anthropic", "ok": True, "detail": f"{cfg.analysis_model()} reachable"}
    except Exception as exc:
        return {"source": "anthropic", "ok": False, "detail": redact(str(exc))[:200]}


_TESTS = {"github": test_github, "notion": test_notion,
          "gmail": test_gmail, "anthropic": test_anthropic}


def test_connector(name: str, cfg: Config) -> dict:
    fn = _TESTS.get(name)
    if not fn:
        return {"source": name, "ok": False, "detail": "unknown connector"}
    return fn(cfg)
