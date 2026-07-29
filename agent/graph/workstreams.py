"""Deterministic workstream resolution.

A workstream is the durable unit of attention (a repository, a Notion
database or standalone page, a configured initiative). Events are assigned
by rules in strict priority order; the only place ambiguity can arise —
email — either links on exactly one strong signal or lands in the
link-review queue. Nothing is guessed silently.

Resolution order per event:
  1. Existing member key (repo, page, database, thread, sender domain)
  2. Auto-anchor creation (repos, Notion databases/pages)
  3. Email only: alias whole-word match on subject+snippet
       exactly one workstream  → link the thread (durable) and assign
       multiple workstreams    → link_suggestions review queue, stay unassigned
  4. Email only: explicit repo URL mention → link the thread and assign
"""

import logging
import re

from agent.config import Config
from agent.store import db

logger = logging.getLogger(__name__)

_REPO_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _domain_of(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender or "")
    return match.group(1).lower() if match else ""


def seed_from_config(cfg: Config, db_path=None) -> None:
    """User-declared initiatives: name, aliases, sender domains."""
    kwargs = {"db_path": db_path} if db_path else {}
    for entry in cfg.get("workstreams", default=[]) or []:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        ws_id = f"custom:{_slug(name)}"
        db.upsert_workstream(ws_id, name, "initiative", **kwargs)
        db.add_workstream_member(ws_id, "alias", name.lower(), **kwargs)
        for alias in entry.get("aliases", []) or []:
            db.add_workstream_member(ws_id, "alias", str(alias).lower(), **kwargs)
        for domain in entry.get("sender_domains", []) or []:
            db.add_workstream_member(ws_id, "sender_domain", str(domain).lower(), **kwargs)


def _ensure_anchor(event: dict, member_map: dict, db_path=None) -> str | None:
    """Create the deterministic anchor workstream for repo/Notion events."""
    kwargs = {"db_path": db_path} if db_path else {}
    meta = event.get("metadata") or {}

    if event["source"] == "github":
        repo = meta.get("repo")
        if not repo:
            return None
        key = ("github_repo", repo)
        if key not in member_map:
            ws_id = f"repo:{repo}"
            name = repo.split("/")[-1]
            db.upsert_workstream(ws_id, name, "repository", **kwargs)
            db.add_workstream_member(ws_id, "github_repo", repo, **kwargs)
            db.add_workstream_member(ws_id, "alias", name.lower(), **kwargs)
            member_map[key] = ws_id
            member_map[("alias", name.lower())] = ws_id
        return member_map[key]

    if event["source"] == "notion":
        database_id = meta.get("database_id") or ""
        page_id = meta.get("page_id") or ""
        if database_id:
            key = ("notion_db", database_id)
            if key not in member_map:
                ws_id = f"notion-db:{database_id}"
                db.upsert_workstream(ws_id, f"Notion DB {database_id[:8]}", "notion_database", **kwargs)
                db.add_workstream_member(ws_id, "notion_db", database_id, **kwargs)
                member_map[key] = ws_id
            return member_map[key]
        if page_id:
            key = ("notion_page", page_id)
            if key not in member_map:
                title = (event.get("title") or "").strip() or f"Notion page {page_id[:8]}"
                ws_id = f"notion-page:{page_id}"
                db.upsert_workstream(ws_id, title, "notion_page", **kwargs)
                db.add_workstream_member(ws_id, "notion_page", page_id, **kwargs)
                if title:
                    db.add_workstream_member(ws_id, "alias", title.lower(), **kwargs)
                    member_map[("alias", title.lower())] = ws_id
                member_map[key] = ws_id
            return member_map[key]
    return None


def _alias_matches(text: str, member_map: dict) -> set[str]:
    """Workstreams whose alias appears as a whole word in the text."""
    lowered = text.lower()
    hits = set()
    for (member_type, key), ws_id in member_map.items():
        if member_type != "alias" or len(key) < 3:
            continue
        if re.search(rf"(?<![\w]){re.escape(key)}(?![\w])", lowered):
            hits.add(ws_id)
    return hits


def _resolve_email(event: dict, member_map: dict, db_path=None) -> str | None:
    kwargs = {"db_path": db_path} if db_path else {}
    meta = event.get("metadata") or {}
    thread_id = meta.get("thread_id") or ""

    if thread_id and ("gmail_thread", thread_id) in member_map:
        return member_map[("gmail_thread", thread_id)]

    domain = _domain_of(meta.get("sender", ""))
    if domain and ("sender_domain", domain) in member_map:
        return member_map[("sender_domain", domain)]

    text = f"{event.get('title') or ''} {meta.get('snippet') or ''}"
    matches = _alias_matches(text, member_map)

    if len(matches) == 1:
        ws_id = next(iter(matches))
        if thread_id:
            db.add_workstream_member(ws_id, "gmail_thread", thread_id, **kwargs)
            member_map[("gmail_thread", thread_id)] = ws_id
        return ws_id

    if len(matches) > 1:
        # Ambiguous: queue every candidate for review, assign nothing.
        for ws_id in sorted(matches):
            db.add_link_suggestion(ws_id, "gmail_thread", thread_id or event["id"],
                                   [event["id"]], round(1 / len(matches), 2), **kwargs)
        return None

    url_match = _REPO_URL_RE.search(text)
    if url_match:
        key = ("github_repo", url_match.group(1))
        ws_id = member_map.get(key)
        if ws_id:
            if thread_id:
                db.add_workstream_member(ws_id, "gmail_thread", thread_id, **kwargs)
                member_map[("gmail_thread", thread_id)] = ws_id
            return ws_id
    return None


def resolve_events(events: list[dict], cfg: Config | None = None, db_path=None) -> dict[str, str]:
    """
    Assign workstreams to the given event rows. Returns {event_id: ws_id}
    for every event that resolved; unresolved events stay unassigned.
    Persists assignments and any new anchors/links.
    """
    kwargs = {"db_path": db_path} if db_path else {}
    if cfg is not None:
        seed_from_config(cfg, db_path=db_path)
    member_map = db.get_member_map(**kwargs)

    assignments: dict[str, str] = {}
    for event in events:
        ws_id = None
        if event["source"] in ("github", "notion"):
            ws_id = _ensure_anchor(event, member_map, db_path=db_path)
        elif event["source"] == "gmail":
            ws_id = _resolve_email(event, member_map, db_path=db_path)
        if ws_id:
            assignments[event["id"]] = ws_id

    if assignments:
        db.assign_event_workstreams(assignments, **kwargs)
    return assignments
