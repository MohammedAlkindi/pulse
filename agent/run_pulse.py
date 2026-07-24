"""Pulse CLI entry point.

Usage:
  python agent/run_pulse.py --config config/pulse_config.yaml
  python agent/run_pulse.py --config config/pulse_config.yaml --dry-run
  python agent/run_pulse.py --config config/pulse_config.yaml --send
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python agent/run_pulse.py` from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import manifest
from agent.config import load_config
from agent.health import check as health_check
from agent.paths import ensure_dirs
from agent.scheduler import _current_week, run_ingestion
from agent.store.db import count_events_for_week, init_db


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pulse — personal intelligence agent")
    p.add_argument("--config", required=True, help="Path to pulse_config.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="Ingest only — no analysis, no briefing")
    p.add_argument("--send", action="store_true",
                   help="Deliver briefing via email (requires briefing.enabled: true)")
    return p.parse_args()


def _print_summary(
    source_counts: dict[str, int],
    total_new: int,
    analysis_status: str,
    briefing_path: str | None,
    delivered: bool,
) -> None:
    source_str = ", ".join(
        f"{src} ({n})" for src, n in sorted(source_counts.items())
    ) or "none"

    print()
    print("  Sources ingested:  ", source_str)
    print("  New events stored: ", total_new)
    print("  Analysis:          ", analysis_status)
    print("  Briefing:          ", briefing_path or "skipped")
    print("  Delivered:         ", "yes" if delivered else "skipped (--send not passed)")
    print()


def main() -> None:
    _setup_logging()
    args = _parse_args()

    ensure_dirs()
    init_db()

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    health = health_check(cfg)
    if health["status"] == "failed":
        print("\nHealth check FAILED — Pulse cannot start:")
        for c in health["checks"]:
            if c["status"] != "ok":
                print(f"  MISSING: {c['name']}")
        sys.exit(1)
    elif health["status"] == "degraded":
        _log = logging.getLogger(__name__)
        for c in health["checks"]:
            if c["status"] != "ok":
                _log.warning("[health] non-critical check failed: %s", c["name"])

    week = _current_week()
    flags = {"dry_run": args.dry_run, "send": args.send}
    manifest.run_start(args.config, flags)

    # ── ingestion ────────────────────────────────────────────────────────────
    source_counts = run_ingestion(cfg)
    total_new = sum(source_counts.values())

    if args.dry_run:
        _print_summary(source_counts, total_new, "skipped (--dry-run)", None, False)
        manifest.run_end({"status": "dry_run", "new_events": total_new})
        return

    # ── analysis + briefing ──────────────────────────────────────────────────
    from agent.scheduler import run_analysis_and_briefing
    from agent.paths import BRIEFING_DRAFT

    try:
        content = run_analysis_and_briefing(cfg, week, send=args.send)
        analysis_status = "complete"
        briefing_path = str(BRIEFING_DRAFT) if content else None
    except Exception as exc:
        logging.getLogger(__name__).error("briefing generation failed: %s", exc)
        analysis_status = f"failed: {exc}"
        briefing_path = None
        content = None

    delivered = args.send and content is not None
    _print_summary(source_counts, total_new, analysis_status, briefing_path, delivered)
    manifest.run_end({
        "status": "complete",
        "week": week,
        "new_events": total_new,
        "delivered": delivered,
    })


if __name__ == "__main__":
    main()
