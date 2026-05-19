"""Notion ingestion: pages created/updated in the last N days.

Assumptions:
- Uses the Notion Search API to find pages modified since the cutoff date.
  The API does not support filtering by created_time, only last_edited_time,
  so we use last_edited_time as the occurred_at timestamp.
- Database entries (child_page or child_database objects) are treated the same
  as regular pages; the parent type is stored in metadata.
- Title is extracted from the first 'title' property found in the page object.
- Notion's search endpoint paginates with cursor; we walk all pages.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from agent.config import Config
from agent.retry import with_retry
from agent.store.models import Event, iso_week

logger = logging.getLogger(__name__)

_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


@with_retry(label="Notion search", max_attempts=3, retryable=(requests.RequestException,))
def _search(token: str, start_cursor: str | None = None) -> dict:
    body: dict[str, Any] = {
        "filter": {"value": "page", "property": "object"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        "page_size": 100,
    }
    if start_cursor:
        body["start_cursor"] = start_cursor
    resp = requests.post(f"{_BASE}/search", headers=_headers(token), json=body, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _extract_title(page: dict) -> str:
    """Walk the page's properties to find the first title-type property."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            if parts:
                return "".join(p.get("plain_text", "") for p in parts)[:200]

    # Fall back to the page's own title field (child_database titles)
    title_obj = page.get("title", [])
    if title_obj:
        return "".join(p.get("plain_text", "") for p in title_obj)[:200]

    return "(untitled)"


def _extract_status(page: dict) -> str | None:
    """Return the value of the first 'status' or 'select' property, or None."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "status":
            s = prop.get("status")
            return s.get("name") if s else None
        if prop.get("type") == "select":
            s = prop.get("select")
            return s.get("name") if s else None
    return None


def _page_to_event(page: dict, cutoff: datetime) -> Event | None:
    last_edited = page.get("last_edited_time", "")
    if not last_edited:
        return None

    try:
        occurred = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
    except ValueError:
        return None

    if occurred < cutoff:
        return None

    created_time = page.get("created_time", "")
    is_new = False
    if created_time:
        try:
            created = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            is_new = created >= cutoff
        except ValueError:
            pass

    parent = page.get("parent", {})
    parent_type = parent.get("type", "unknown")
    database_id = parent.get("database_id", "") if parent_type == "database_id" else ""

    return Event(
        id=f"notion:{page['id']}:{last_edited}",
        source="notion",
        event_type="page_created" if is_new else "page_updated",
        title=_extract_title(page),
        metadata={
            "page_id": page["id"],
            "parent_type": parent_type,
            "database_id": database_id,
            "status": _extract_status(page),
            "url": page.get("url", ""),
            "last_edited_time": last_edited,
        },
        occurred_at=occurred.isoformat(),
        week_number=iso_week(occurred),
    )


def fetch(cfg: Config) -> list[Event]:
    source_cfg = cfg.source_cfg("notion")
    lookback_days: int = source_cfg.get("lookback_days", 7)

    try:
        token = cfg.env(source_cfg.get("token_env", "NOTION_TOKEN"))
    except EnvironmentError as exc:
        logger.error("[notion] %s", exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    events: list[Event] = []
    cursor = None

    while True:
        try:
            resp = _search(token, cursor)
        except Exception as exc:
            logger.error("[notion] search failed: %s", exc)
            break

        for page in resp.get("results", []):
            try:
                evt = _page_to_event(page, cutoff)
                if evt:
                    events.append(evt)
            except Exception as exc:
                logger.warning("[notion] skipping page %s: %s", page.get("id"), exc)

        if not resp.get("has_more"):
            break

        # If all pages on this batch are older than cutoff, stop paginating
        results = resp.get("results", [])
        if results:
            oldest = results[-1].get("last_edited_time", "")
            if oldest:
                try:
                    oldest_dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
                    if oldest_dt < cutoff:
                        break
                except ValueError:
                    pass

        cursor = resp.get("next_cursor")
        if not cursor:
            break

    logger.info("[notion] fetched %d events", len(events))
    return events
