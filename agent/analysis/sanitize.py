"""Treat all source text as hostile data.

Two rendering boundaries need protection:

* the analysis prompt, where text that mimics the <event> framing could
  forge context boundaries or fake evidence ids;
* the Markdown briefing, where raw HTML, links, and control characters
  could execute or mislead when the briefing is emailed or displayed.

Both strip the dangerous shapes rather than escaping them, because the
downstream consumers (a model, a Markdown renderer) interpret escapes
inconsistently. Trust classification lives here too: content from unknown
external senders is labeled so the briefing can show it as claimed rather
than established.
"""

import re

_TAGISH = re.compile(r"</?\s*(event|events|system|assistant|user|instructions?|tool_use|tool_result)\b[^>]*>",
                     re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>\n]{1,200}>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MD_LINK = re.compile(r"\[([^\]]{0,200})\]\((?:javascript|data|vbscript):[^)]*\)", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```", re.MULTILINE)

# Phrases that only exist to steer a model. Kept visible but defanged, so a
# reviewer can still see what the sender tried.
_DIRECTIVE = re.compile(
    r"\b(ignore (?:all )?(?:previous|prior|above) instructions?|"
    r"disregard (?:all )?(?:previous|prior) instructions?|"
    r"system prompt|you are now|new instructions?:)",
    re.IGNORECASE,
)


def sanitize_for_prompt(text: str, limit: int = 1000) -> str:
    """Neutralise context-boundary forgery before text enters a prompt."""
    if not text:
        return ""
    cleaned = _TAGISH.sub("[removed-tag]", text)
    cleaned = _CONTROL.sub(" ", cleaned)
    cleaned = _DIRECTIVE.sub("[removed-directive]", cleaned)
    return cleaned[:limit]


def sanitize_for_markdown(text: str, limit: int = 400) -> str:
    """Neutralise markup before text is rendered into the briefing."""
    if not text:
        return ""
    cleaned = _CONTROL.sub(" ", text)
    cleaned = _MD_LINK.sub(r"\1 [link removed]", cleaned)
    cleaned = _HTML_TAG.sub("", cleaned)
    cleaned = _FENCE.sub("", cleaned)
    cleaned = cleaned.replace("|", "\\|")            # keep tables intact
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def looks_like_injection(text: str) -> bool:
    """True when source text tries to issue instructions or forge framing."""
    if not text:
        return False
    return bool(_DIRECTIVE.search(text) or _TAGISH.search(text))


_SEVERITY = {"normal": 0, "external": 1, "suspicious": 2}


def most_severe(*levels: str) -> str:
    """Trust never downgrades: a stored 'normal' default must not mask a
    content-based 'suspicious' classification."""
    return max((l for l in levels if l), key=lambda l: _SEVERITY.get(l, 0), default="normal")


def classify_sensitivity(event: dict, known_domains: set[str] | None = None) -> str:
    """
    'suspicious' — content attempts instruction or framing injection
    'external'   — from a sender outside the user's known/config domains
    'normal'     — everything else
    """
    meta = event.get("metadata") or {}
    text = f"{event.get('title') or ''} {meta.get('snippet') or ''}"
    if looks_like_injection(text):
        return "suspicious"
    if event.get("source") == "gmail" and event.get("event_type") == "email_received":
        sender = meta.get("sender", "")
        match = re.search(r"@([\w.-]+)", sender or "")
        domain = match.group(1).lower() if match else ""
        if domain and known_domains and domain not in known_domains:
            return "external"
        if not known_domains:
            return "external"
    return "normal"
