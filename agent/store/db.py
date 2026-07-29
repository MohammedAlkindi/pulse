"""SQLite connection, migrations, and CRUD operations."""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from agent.paths import DB_PATH
from agent.store.migrations import apply_migrations
from agent.store.models import Briefing, Event

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(db_path) as con:
        apply_migrations(con)
    logger.debug("Database initialised at %s", db_path)


def _parse_meta(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _row_to_event_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["metadata"] = _parse_meta(d.get("metadata"))
    return d


def _fts_text(event: Event) -> tuple[str, str]:
    snippet = ""
    meta = event.metadata or {}
    for key in ("snippet", "description", "status"):
        val = meta.get(key)
        if isinstance(val, str) and val:
            snippet = val
            break
    return event.title or "", snippet


# ── events ──────────────────────────────────────────────────────────────────

def upsert_events(events: list[Event], db_path: Path = DB_PATH) -> tuple[int, int]:
    """
    Idempotent, transactional bulk write. New events insert; existing events
    whose content hash changed are updated in place (ingested_at preserved,
    source_updated_at stamped). Returns (new, updated).
    """
    new = updated = 0
    with _conn(db_path) as con:
        for event in events:
            digest = event.hash()
            row = con.execute(
                "SELECT content_hash FROM events WHERE id = ?", (event.id,)
            ).fetchone()
            if row is None:
                con.execute(
                    """INSERT INTO events
                       (id, source, event_type, title, metadata, occurred_at, ingested_at,
                        week_number, actor, canonical_url, content_hash, source_updated_at,
                        sensitivity, deleted)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event.id, event.source, event.event_type, event.title,
                     json.dumps(event.metadata), event.occurred_at, event.ingested_at,
                     event.week_number, event.actor, event.canonical_url, digest,
                     event.source_updated_at, event.sensitivity, event.deleted),
                )
                title, snippet = _fts_text(event)
                con.execute(
                    "INSERT INTO events_fts (event_id, title, snippet) VALUES (?, ?, ?)",
                    (event.id, title, snippet),
                )
                new += 1
            elif row["content_hash"] != digest:
                con.execute(
                    """UPDATE events SET title = ?, metadata = ?, actor = ?,
                       canonical_url = ?, content_hash = ?, source_updated_at = ?
                       WHERE id = ?""",
                    (event.title, json.dumps(event.metadata), event.actor,
                     event.canonical_url, digest,
                     event.source_updated_at or _now(), event.id),
                )
                title, snippet = _fts_text(event)
                con.execute("DELETE FROM events_fts WHERE event_id = ?", (event.id,))
                con.execute(
                    "INSERT INTO events_fts (event_id, title, snippet) VALUES (?, ?, ?)",
                    (event.id, title, snippet),
                )
                updated += 1
    return new, updated


def insert_event(event: Event, db_path: Path = DB_PATH) -> bool:
    """Single-event convenience wrapper; True when the event was new."""
    new, _ = upsert_events([event], db_path)
    return new > 0


def get_events_for_week(week: str, db_path: Path = DB_PATH) -> list[dict]:
    sql = "SELECT * FROM events WHERE week_number = ? AND deleted = 0 ORDER BY occurred_at, id"
    with _conn(db_path) as con:
        rows = con.execute(sql, (week,)).fetchall()
    return [_row_to_event_dict(r) for r in rows]


def get_events_for_weeks(weeks: list[str], db_path: Path = DB_PATH) -> list[dict]:
    """Light rows (source, title, metadata, week_number) across several weeks,
    for momentum computation."""
    if not weeks:
        return []
    placeholders = ",".join("?" * len(weeks))
    sql = (f"SELECT source, title, metadata, week_number FROM events "
           f"WHERE week_number IN ({placeholders}) AND deleted = 0")
    with _conn(db_path) as con:
        rows = con.execute(sql, weeks).fetchall()
    return [_row_to_event_dict(r) for r in rows]


def get_events_by_ids(ids: list[str], db_path: Path = DB_PATH) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    sql = f"SELECT * FROM events WHERE id IN ({placeholders}) ORDER BY occurred_at, id"
    with _conn(db_path) as con:
        rows = con.execute(sql, ids).fetchall()
    return [_row_to_event_dict(r) for r in rows]


def count_events_for_week(week: str, db_path: Path = DB_PATH) -> dict[str, int]:
    sql = ("SELECT source, COUNT(*) as n FROM events "
           "WHERE week_number = ? AND deleted = 0 GROUP BY source")
    with _conn(db_path) as con:
        rows = con.execute(sql, (week,)).fetchall()
    return {row["source"]: row["n"] for row in rows}


def count_events_by_type_for_week(week: str, db_path: Path = DB_PATH) -> dict[str, dict[str, int]]:
    """Return {source: {event_type: count}} for one week."""
    sql = """
        SELECT source, event_type, COUNT(*) as n
        FROM events WHERE week_number = ? AND deleted = 0
        GROUP BY source, event_type
    """
    with _conn(db_path) as con:
        rows = con.execute(sql, (week,)).fetchall()
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        result.setdefault(row["source"], {})[row["event_type"]] = row["n"]
    return result


def search_events(query: str, limit: int = 50, db_path: Path = DB_PATH) -> list[dict]:
    """Full-text search over titles and snippets. Query syntax is neutralised:
    every token is quoted so FTS operators in user input cannot break the query."""
    tokens = [t.replace('"', "") for t in query.split() if t.strip('"')]
    if not tokens:
        return []
    match = " OR ".join(f'"{t}"' for t in tokens)
    sql = """
        SELECT e.* FROM events_fts f
        JOIN events e ON e.id = f.event_id
        WHERE events_fts MATCH ? AND e.deleted = 0
        ORDER BY bm25(events_fts), e.occurred_at DESC
        LIMIT ?
    """
    with _conn(db_path) as con:
        rows = con.execute(sql, (match, limit)).fetchall()
    return [_row_to_event_dict(r) for r in rows]


# ── sync state ──────────────────────────────────────────────────────────────

def get_sync_state(source: str, db_path: Path = DB_PATH) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM sync_state WHERE source = ?", (source,)).fetchone()
    return dict(row) if row else None


def set_sync_state(source: str, *, cursor_ts: str | None = None, status: str,
                   error: str = "", db_path: Path = DB_PATH) -> None:
    now = _now()
    with _conn(db_path) as con:
        existing = con.execute("SELECT cursor_ts FROM sync_state WHERE source = ?", (source,)).fetchone()
        keep_cursor = existing["cursor_ts"] if existing else ""
        new_cursor = cursor_ts if cursor_ts is not None else keep_cursor
        success_at = now if status == "ok" else ""
        if existing:
            con.execute(
                """UPDATE sync_state SET cursor_ts = ?, last_status = ?, last_error = ?,
                   last_success_at = CASE WHEN ? != '' THEN ? ELSE last_success_at END
                   WHERE source = ?""",
                (new_cursor, status, error, success_at, success_at, source),
            )
        else:
            con.execute(
                """INSERT INTO sync_state (source, cursor_ts, last_success_at, last_status, last_error)
                   VALUES (?, ?, ?, ?, ?)""",
                (source, new_cursor, success_at, status, error),
            )


def all_sync_states(db_path: Path = DB_PATH) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("SELECT * FROM sync_state ORDER BY source").fetchall()
    return [dict(r) for r in rows]


# ── workstreams ─────────────────────────────────────────────────────────────

def upsert_workstream(ws_id: str, name: str, kind: str, db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO workstreams (id, name, kind, created_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name = excluded.name""",
            (ws_id, name, kind, _now()),
        )


def add_workstream_member(ws_id: str, member_type: str, member_key: str,
                          origin: str = "deterministic", db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            """INSERT OR IGNORE INTO workstream_members
               (workstream_id, member_type, member_key, origin) VALUES (?, ?, ?, ?)""",
            (ws_id, member_type, member_key, origin),
        )


def get_member_map(db_path: Path = DB_PATH) -> dict[tuple[str, str], str]:
    with _conn(db_path) as con:
        rows = con.execute("SELECT workstream_id, member_type, member_key FROM workstream_members").fetchall()
    return {(r["member_type"], r["member_key"]): r["workstream_id"] for r in rows}


def list_workstreams(db_path: Path = DB_PATH) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute("SELECT * FROM workstreams ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def add_link_suggestion(ws_id: str, member_type: str, member_key: str,
                        evidence: list[str], confidence: float,
                        db_path: Path = DB_PATH) -> str:
    sug_id = str(uuid.uuid4())
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO link_suggestions
               (id, workstream_id, member_type, member_key, evidence, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sug_id, ws_id, member_type, member_key, json.dumps(evidence), confidence, _now()),
        )
    return sug_id


def list_link_suggestions(status: str = "pending", db_path: Path = DB_PATH) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM link_suggestions WHERE status = ? ORDER BY confidence DESC", (status,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["evidence"] = _parse_meta(d["evidence"]) if d["evidence"].startswith("{") else json.loads(d["evidence"] or "[]")
        result.append(d)
    return result


# ── items (decisions, commitments, risks) ───────────────────────────────────

def insert_item(item: dict, db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO items
               (id, kind, text, workstream_id, counterparty, due_date, status,
                evidence, confidence, first_week, last_week, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["id"], item["kind"], item["text"], item.get("workstream_id", ""),
             item.get("counterparty", ""), item.get("due_date", ""),
             item.get("status", "open"), json.dumps(item.get("evidence", [])),
             json.dumps(item.get("confidence", {})), item["first_week"],
             item["last_week"], _now(), _now()),
        )


def update_item(item_id: str, *, status: str | None = None, last_week: str | None = None,
                evidence: list[str] | None = None, due_date: str | None = None,
                db_path: Path = DB_PATH) -> None:
    sets, params = ["updated_at = ?"], [_now()]
    if status is not None:
        sets.append("status = ?"); params.append(status)
    if last_week is not None:
        sets.append("last_week = ?"); params.append(last_week)
    if evidence is not None:
        sets.append("evidence = ?"); params.append(json.dumps(evidence))
    if due_date is not None:
        sets.append("due_date = ?"); params.append(due_date)
    params.append(item_id)
    with _conn(db_path) as con:
        con.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", params)


def list_items(kind: str | None = None, status: str | None = None,
               db_path: Path = DB_PATH) -> list[dict]:
    clauses, params = [], []
    if kind:
        clauses.append("kind = ?"); params.append(kind)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn(db_path) as con:
        rows = con.execute(
            f"SELECT * FROM items {where} ORDER BY due_date = '', due_date, created_at", params
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d["evidence"] or "[]")
        d["confidence"] = _parse_meta(d["confidence"])
        result.append(d)
    return result


def append_item_history(item_id: str, week: str, change: str, detail: str = "",
                        evidence: list[str] | None = None, db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO item_history (item_id, week, change, detail, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item_id, week, change, detail, json.dumps(evidence or []), _now()),
        )


def get_item_history(item_id: str, db_path: Path = DB_PATH) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM item_history WHERE item_id = ? ORDER BY seq", (item_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── briefings ────────────────────────────────────────────────────────────────

def insert_briefing(briefing: Briefing, db_path: Path = DB_PATH) -> None:
    sql = """
        INSERT OR REPLACE INTO briefings (id, week_number, generated_at, delivered, content)
        VALUES (?, ?, ?, ?, ?)
    """
    with _conn(db_path) as con:
        con.execute(sql, (
            briefing.id,
            briefing.week_number,
            briefing.generated_at,
            briefing.delivered,
            briefing.content,
        ))


def mark_delivered(briefing_id: str, db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            "UPDATE briefings SET delivered = 1 WHERE id = ?",
            (briefing_id,),
        )


def get_briefing_for_week(week: str, db_path: Path = DB_PATH) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM briefings WHERE week_number = ? ORDER BY generated_at DESC LIMIT 1",
            (week,),
        ).fetchone()
    return dict(row) if row else None


def list_briefings(db_path: Path = DB_PATH) -> list[dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT id, week_number, generated_at, delivered FROM briefings ORDER BY week_number DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── retention ────────────────────────────────────────────────────────────────

def export_all(db_path: Path = DB_PATH) -> dict:
    """Full local export of user data as plain dicts."""
    out: dict[str, list[dict]] = {}
    with _conn(db_path) as con:
        for table in ("events", "briefings", "workstreams", "workstream_members",
                      "items", "item_history", "sync_state", "link_suggestions"):
            rows = con.execute(f"SELECT * FROM {table}").fetchall()
            out[table] = [dict(r) for r in rows]
    return out


def purge_all(db_path: Path = DB_PATH) -> None:
    """Complete local deletion of derived and source data."""
    with _conn(db_path) as con:
        for table in ("events", "events_fts", "briefings", "workstreams",
                      "workstream_members", "items", "item_history",
                      "sync_state", "link_suggestions"):
            con.execute(f"DELETE FROM {table}")
