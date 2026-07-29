"""Credential resolution and redaction.

Resolution order, first hit wins:
  1. environment variable  — automation, CI, scheduled runs
  2. OS keychain           — interactive machines, when `keyring` is installed

Secrets are never written to the ledger, the briefing, the manifest, or logs.
`redact()` is the chokepoint every diagnostic path runs through; `mask()` is
for anything the UI displays.
"""

import logging
import re

logger = logging.getLogger(__name__)

SERVICE = "pulse"

# Shapes worth scrubbing even when we do not know the value: provider tokens
# and anything that looks like a bearer credential.
_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bntn_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bsecret_[A-Za-z0-9]{20,}\b"),
    re.compile(r"ya29\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)\b(authorization|bearer|api[_-]?key|token)\b\s*[:=]\s*\S+"),
]


def mask(secret: str | None) -> str:
    """Display form: never more than the last four characters."""
    if not secret:
        return "(not set)"
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:3]}…{secret[-4:]}"


def redact(text: str, extra: list[str] | None = None) -> str:
    """Scrub known secret values and secret-shaped tokens from any string."""
    if not text:
        return text
    cleaned = str(text)
    for value in (extra or []):
        if value and len(value) >= 8:
            cleaned = cleaned.replace(value, "[redacted]")
    for pattern in _PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned


def keyring_get(name: str) -> str | None:
    try:
        import keyring  # optional dependency
    except ImportError:
        return None
    try:
        return keyring.get_password(SERVICE, name)
    except Exception as exc:  # backend missing or locked
        logger.debug("[secrets] keyring unavailable: %s", exc)
        return None


def keyring_set(name: str, value: str) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(SERVICE, name, value)
        return True
    except Exception as exc:
        logger.warning("[secrets] could not store %s in keychain: %s", name, exc)
        return False


def resolve(name: str, env: dict | None = None) -> str | None:
    """Environment first (automation), then OS keychain (interactive)."""
    import os
    source = env if env is not None else os.environ
    value = source.get(name)
    if value:
        return value
    return keyring_get(name)


def describe(name: str, env: dict | None = None) -> dict:
    """Non-sensitive status for the UI: where a credential came from, masked."""
    import os
    source = env if env is not None else os.environ
    if source.get(name):
        return {"name": name, "configured": True, "origin": "environment",
                "masked": mask(source[name])}
    stored = keyring_get(name)
    if stored:
        return {"name": name, "configured": True, "origin": "keychain", "masked": mask(stored)}
    return {"name": name, "configured": False, "origin": "none", "masked": mask(None)}
