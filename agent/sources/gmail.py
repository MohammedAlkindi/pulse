"""Gmail ingestion: fetches email metadata for the last N days.

Assumptions:
- OAuth credentials follow the Google Desktop App flow (same as Shell workflow).
- Body content is intentionally never fetched or stored; only subject + snippet.
- thread_id is stored so related messages can be grouped during analysis.
- The 'me' special value is used as userId throughout (authenticated user).
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.config import Config
from agent.retry import with_retry
from agent.store.models import Event, iso_week

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _build_service(credentials_path: str, token_path: str):
    """Build Gmail API service, refreshing token if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    tp = Path(token_path)
    if tp.exists():
        creds = Credentials.from_authorized_user_file(str(tp), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, _SCOPES)
            creds = flow.run_local_server(port=0)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


def _extract_event(msg_meta: dict, label: str) -> Event:
    """Convert a Gmail message resource into an Event."""
    headers = _parse_headers(msg_meta.get("payload", {}).get("headers", []))
    msg_id = msg_meta["id"]
    internal_date = int(msg_meta.get("internalDate", 0)) / 1000
    occurred = datetime.fromtimestamp(internal_date, tz=timezone.utc)

    subject = headers.get("subject", "(no subject)")
    sender = headers.get("from", "")
    recipients = headers.get("to", "")
    snippet = msg_meta.get("snippet", "")

    payload = msg_meta.get("payload", {})
    has_attachment = any(
        p.get("filename") for p in payload.get("parts", [])
    )

    metadata = {
        "sender": sender,
        "recipients": recipients,
        "snippet": snippet,
        "thread_id": msg_meta.get("threadId", ""),
        "label": label,
        "has_attachment": has_attachment,
    }

    return Event(
        id=f"gmail:{msg_id}",
        source="gmail",
        event_type="email_sent" if label == "SENT" else "email_received",
        title=subject,
        metadata=metadata,
        occurred_at=occurred.isoformat(),
        week_number=iso_week(occurred),
    )


def fetch(cfg: Config) -> list[Event]:
    """
    Fetch Gmail events for the last N days.
    Returns empty list and logs on any failure.
    """
    source_cfg = cfg.source_cfg("gmail")
    credentials_path = str(Path(cfg.get("sources", "gmail", "credentials_path", default="config/credentials.json")))
    token_path = str(Path(cfg.get("sources", "gmail", "token_path", default="config/token.json")))
    lookback_days: int = source_cfg.get("lookback_days", 7)
    labels: list[str] = source_cfg.get("labels", ["INBOX", "SENT"])

    try:
        service = _build_service(credentials_path, token_path)
    except Exception as exc:
        logger.error("[gmail] failed to build service: %s", exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    after_epoch = int(cutoff.timestamp())

    events: list[Event] = []

    for label in labels:
        try:
            events.extend(_fetch_label(service, label, after_epoch))
        except Exception as exc:
            logger.error("[gmail] failed to fetch label '%s': %s", label, exc)

    logger.info("[gmail] fetched %d events", len(events))
    return events


@with_retry(label="Gmail list messages", max_attempts=3)
def _list_message_ids(service, label: str, after_epoch: int) -> list[str]:
    ids = []
    page_token = None
    query = f"after:{after_epoch}"
    while True:
        kwargs: dict[str, Any] = {
            "userId": "me",
            "labelIds": [label],
            "q": query,
            "maxResults": 500,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


@with_retry(label="Gmail get message", max_attempts=3)
def _get_message(service, msg_id: str) -> dict:
    return service.users().messages().get(
        userId="me",
        id=msg_id,
        format="metadata",
        metadataHeaders=["Subject", "From", "To", "Date"],
    ).execute()


def _fetch_label(service, label: str, after_epoch: int) -> list[Event]:
    ids = _list_message_ids(service, label, after_epoch)
    events = []
    for msg_id in ids:
        try:
            msg = _get_message(service, msg_id)
            events.append(_extract_event(msg, label))
        except Exception as exc:
            logger.warning("[gmail] skipping message %s: %s", msg_id, exc)
    return events
