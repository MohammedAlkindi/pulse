"""Send the briefing email via Gmail API.

Safety rules enforced here:
- The draft is always written to logs/briefing_draft.md first.
- Actual sending only happens when called explicitly (caller must pass send=True).
- The CLI --send flag is the gate; this module never decides to send on its own.
"""

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from agent import paths
from agent.config import Config
from agent.retry import with_retry

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _build_service(credentials_path: str, token_path: str):
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


def _mime_message(sender: str, recipient: str, subject: str, body_md: str) -> dict:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


@with_retry(label="Gmail send", max_attempts=3)
def _send(service, message: dict) -> dict:
    return service.users().messages().send(userId="me", body=message).execute()


def save_draft(content: str) -> Path:
    """Write briefing to logs/briefing_draft.md. Always called before send."""
    draft = paths.BRIEFING_DRAFT  # resolved at call time so demo mode can retarget
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(content, encoding="utf-8")
    logger.info("[emailer] briefing draft saved to %s", draft)
    return draft


def deliver(content: str, week: str, cfg: Config, send: bool = False) -> bool:
    """
    Write the draft, then optionally send.
    Returns True if email was sent, False otherwise.
    """
    save_draft(content)

    if not send:
        logger.info("[emailer] --send not passed; skipping delivery.")
        return False

    briefing_cfg = cfg.briefing
    if not briefing_cfg.get("enabled", False):
        logger.info("[emailer] briefing.enabled is false; skipping delivery.")
        return False

    recipient = briefing_cfg.get("recipient_email", "")
    sender = briefing_cfg.get("sender_email", "")
    if not recipient or not sender:
        logger.error("[emailer] recipient_email and sender_email must be set in config.")
        return False

    credentials_path = str(Path(cfg.get("sources", "gmail", "credentials_path",
                                        default="config/credentials.json")))
    token_path = str(Path(cfg.get("sources", "gmail", "token_path",
                                   default="config/token.json")))

    try:
        service = _build_service(credentials_path, token_path)
    except Exception as exc:
        logger.error("[emailer] failed to build Gmail service: %s", exc)
        return False

    subject = f"Weekly Pulse — {week}"
    message = _mime_message(sender, recipient, subject, content)

    try:
        _send(service, message)
        logger.info("[emailer] briefing delivered to %s", recipient)
        return True
    except Exception as exc:
        logger.error("[emailer] send failed: %s", exc)
        return False
