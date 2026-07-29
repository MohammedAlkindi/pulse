"""GitHub activity ingestion using the REST API v3 with a PAT.

Assumptions:
- Only events for `cfg.sources.github.username` are fetched.
- The GitHub Events API returns at most 300 events (last 90 days cap from GitHub).
  We filter client-side by date rather than relying on that cap.
- PushEvent payloads include up to 20 commits; larger pushes are truncated by GitHub.
- Event IDs from GitHub are stable; we prefix them with 'github:' for the events table.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from agent.config import Config
from agent.retry import with_retry
from agent.store.models import Event, iso_week

logger = logging.getLogger(__name__)

_BASE = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@with_retry(label="GitHub API", max_attempts=3, retryable=(requests.RequestException,))
def _get(url: str, token: str, params: dict | None = None) -> Any:
    resp = requests.get(url, headers=_headers(token), params=params, timeout=20)
    if resp.status_code == 429 or (
        resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0"
    ):
        # Honor the server's pacing (bounded) before the retry decorator fires.
        import time
        retry_after = resp.headers.get("Retry-After", "")
        wait = min(60, int(retry_after)) if retry_after.isdigit() else 30
        logger.warning("[github] rate limited; waiting %ds.", wait)
        time.sleep(wait)
    resp.raise_for_status()
    return resp.json()


def _parse_datetime(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _events_from_push(gh_event: dict, cutoff: datetime) -> list[Event]:
    """Expand a PushEvent into one Event per commit."""
    created_at = _parse_datetime(gh_event["created_at"])
    if created_at < cutoff:
        return []
    repo = gh_event["repo"]["name"]
    payload = gh_event.get("payload", {})
    events = []
    for commit in payload.get("commits", []):
        sha_short = commit["sha"][:8]
        evt = Event(
            id=f"github:commit:{sha_short}:{repo}",
            source="github",
            event_type="commit",
            title=commit.get("message", "").splitlines()[0][:200],
            metadata={
                "repo": repo,
                "sha": commit["sha"],
                "author": commit.get("author", {}).get("name", ""),
                "url": commit.get("url", ""),
            },
            occurred_at=created_at.isoformat(),
            week_number=iso_week(created_at),
            actor=commit.get("author", {}).get("name", ""),
            canonical_url=f"https://github.com/{repo}/commit/{commit['sha']}",
        )
        events.append(evt)
    return events


def _event_from_pr(gh_event: dict, cutoff: datetime) -> Event | None:
    created_at = _parse_datetime(gh_event["created_at"])
    if created_at < cutoff:
        return None
    payload = gh_event.get("payload", {})
    pr = payload.get("pull_request", {})
    action = payload.get("action", "")
    # Only track opened and closed (merged) PRs
    if action not in ("opened", "closed"):
        return None
    pr_number = pr.get("number", 0)
    repo = gh_event["repo"]["name"]
    merged = pr.get("merged", False)
    return Event(
        id=f"github:pr:{repo}:{pr_number}:{action}",
        source="github",
        event_type="pr_merged" if (action == "closed" and merged) else f"pr_{action}",
        title=pr.get("title", "")[:200],
        metadata={
            "repo": repo,
            "number": pr_number,
            "state": pr.get("state", ""),
            "merged": merged,
            "url": pr.get("html_url", ""),
        },
        occurred_at=created_at.isoformat(),
        week_number=iso_week(created_at),
        actor=gh_event.get("actor", {}).get("login", ""),
        canonical_url=pr.get("html_url", ""),
    )


def _event_from_issue(gh_event: dict, cutoff: datetime) -> Event | None:
    created_at = _parse_datetime(gh_event["created_at"])
    if created_at < cutoff:
        return None
    payload = gh_event.get("payload", {})
    action = payload.get("action", "")
    if action not in ("opened", "closed"):
        return None
    issue = payload.get("issue", {})
    issue_number = issue.get("number", 0)
    repo = gh_event["repo"]["name"]
    return Event(
        id=f"github:issue:{repo}:{issue_number}:{action}",
        source="github",
        event_type=f"issue_{action}",
        title=issue.get("title", "")[:200],
        metadata={
            "repo": repo,
            "number": issue_number,
            "state": issue.get("state", ""),
            "url": issue.get("html_url", ""),
        },
        occurred_at=created_at.isoformat(),
        week_number=iso_week(created_at),
        actor=gh_event.get("actor", {}).get("login", ""),
        canonical_url=issue.get("html_url", ""),
    )


def _event_from_create(gh_event: dict, cutoff: datetime) -> Event | None:
    """CreateEvent covers repo creation (ref_type == 'repository')."""
    created_at = _parse_datetime(gh_event["created_at"])
    if created_at < cutoff:
        return None
    payload = gh_event.get("payload", {})
    if payload.get("ref_type") != "repository":
        return None
    repo = gh_event["repo"]["name"]
    return Event(
        id=f"github:repo_created:{repo}",
        source="github",
        event_type="repo_created",
        title=repo,
        metadata={
            "repo": repo,
            "description": payload.get("description", ""),
        },
        occurred_at=created_at.isoformat(),
        week_number=iso_week(created_at),
        actor=gh_event.get("actor", {}).get("login", ""),
        canonical_url=f"https://github.com/{repo}",
    )


_HANDLERS = {
    "PushEvent": _events_from_push,
    "PullRequestEvent": lambda e, c: [r] if (r := _event_from_pr(e, c)) else [],
    "IssuesEvent": lambda e, c: [r] if (r := _event_from_issue(e, c)) else [],
    "CreateEvent": lambda e, c: [r] if (r := _event_from_create(e, c)) else [],
}


def fetch(cfg: Config, since: datetime | None = None) -> list[Event]:
    """Fetch GitHub events since `since` (or the configured lookback).
    Raises on total failure so the scheduler can record a real error;
    per-event problems are skipped with a warning."""
    source_cfg = cfg.source_cfg("github")
    username: str = source_cfg.get("username", "")
    lookback_days: int = source_cfg.get("lookback_days", 7)

    if not username:
        raise ValueError("github: 'username' is required in config but not set.")

    token = cfg.env(source_cfg.get("token_env", "GITHUB_TOKEN"))

    cutoff = since or (datetime.now(timezone.utc) - timedelta(days=lookback_days))
    events: list[Event] = []

    gh_events = _paginate_events(username, token)

    for gh_event in gh_events:
        event_type = gh_event.get("type", "")
        handler = _HANDLERS.get(event_type)
        if handler:
            try:
                events.extend(handler(gh_event, cutoff))
            except Exception as exc:
                logger.warning("[github] skipping event %s: %s", gh_event.get("id"), exc)

    logger.info("[github] fetched %d events", len(events))
    return events


def _paginate_events(username: str, token: str) -> list[dict]:
    """Fetch up to 3 pages (300 events) from the user events endpoint."""
    url = f"{_BASE}/users/{username}/events"
    all_events = []
    for page in range(1, 4):
        batch = _get(url, token, params={"per_page": 100, "page": page})
        if not batch:
            break
        all_events.extend(batch)
        if len(batch) < 100:
            break
    return all_events
