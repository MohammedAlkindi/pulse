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
    p.add_argument("--config", help="Path to pulse_config.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="Ingest only — no analysis, no briefing")
    p.add_argument("--send", action="store_true",
                   help="Deliver briefing via email (requires briefing.enabled: true)")
    p.add_argument("--demo", action="store_true",
                   help="Run the synthetic corpus end-to-end; no credentials, writes to data/demo/")
    p.add_argument("--export", metavar="PATH",
                   help="Write a full JSON export of local data to PATH and exit")
    p.add_argument("--purge", action="store_true",
                   help="Delete all local Pulse data (events, items, briefings) and exit")
    args = p.parse_args()
    if not args.config and not (args.demo or args.export or args.purge):
        p.error("--config is required unless running --demo, --export, or --purge")
    return args


def _print_summary(
    source_results: dict[str, dict],
    total_new: int,
    analysis_status: str,
    briefing_path: str | None,
    delivered: bool,
) -> None:
    def label(src: str, r: dict) -> str:
        if r["status"] == "disabled":
            return f"{src} (off)"
        if r["status"] == "error":
            return f"{src} (FAILED)"
        return f"{src} ({r['new']} new, {r['updated']} updated)"

    source_str = ", ".join(
        label(src, r) for src, r in sorted(source_results.items())
    ) or "none"

    print()
    print("  Sources ingested:  ", source_str)
    print("  New events stored: ", total_new)
    print("  Analysis:          ", analysis_status)
    print("  Briefing:          ", briefing_path or "skipped")
    print("  Delivered:         ", "yes" if delivered else "skipped (--send not passed)")
    print()


def _run_demo() -> None:
    from agent.demo.runner import run, use_demo_paths

    demo_root = use_demo_paths()
    print(f"\n  Demo mode — synthetic data only, written to {demo_root}\n")
    summary = run()
    print(f"  Corpus events:     {summary['submitted']} submitted, {summary['new']} new")
    print(f"  Workstreams:       {summary['workstreams']}")
    print(f"  Open items:        {summary['open_items']}")
    print(f"  Week:              {summary['week']}")
    print(f"  Briefing:          {summary['briefing_path']}\n")


def main() -> None:
    _setup_logging()
    args = _parse_args()

    if args.demo:
        ensure_dirs()
        _run_demo()
        return

    ensure_dirs()
    init_db()

    if args.export:
        import json
        from agent.store.db import export_all
        Path(args.export).write_text(json.dumps(export_all(), indent=2), encoding="utf-8")
        print(f"\n  Exported all local Pulse data to {args.export}\n")
        return

    if args.purge:
        from agent.store.db import purge_all
        purge_all()
        print("\n  All local Pulse data deleted (events, items, briefings, sync state).\n")
        return

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    health = health_check(cfg, require_analysis=not args.dry_run)
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
    source_results = run_ingestion(cfg)
    total_new = sum(r["new"] for r in source_results.values())

    if args.dry_run:
        _print_summary(source_results, total_new, "skipped (--dry-run)", None, False)
        manifest.run_end({"status": "dry_run", "new_events": total_new})
        return

    # ── analysis + briefing ──────────────────────────────────────────────────
    from agent.scheduler import run_analysis_and_briefing
    from agent.paths import BRIEFING_DRAFT

    try:
        content = run_analysis_and_briefing(cfg, week, send=args.send,
                                            source_status=source_results)
        analysis_status = "complete"
        briefing_path = str(BRIEFING_DRAFT) if content else None
    except Exception as exc:
        logging.getLogger(__name__).error("briefing generation failed: %s", exc)
        analysis_status = f"failed: {exc}"
        briefing_path = None
        content = None

    delivered = args.send and content is not None
    _print_summary(source_results, total_new, analysis_status, briefing_path, delivered)
    manifest.run_end({
        "status": "complete",
        "week": week,
        "new_events": total_new,
        "delivered": delivered,
    })


if __name__ == "__main__":
    main()
