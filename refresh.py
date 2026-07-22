"""
intuixion.ai — Monthly Corpus Refresh

Runs the full collect → ingest pipeline, then emails a summary if
SMTP credentials are configured. Designed to be called by Windows
Task Scheduler or any cron-equivalent on a monthly cadence.

Usage:
    python refresh.py               # collect all + ingest new files only
    python refresh.py --sector financial  # one sector
    python refresh.py --dry-run     # simulate without downloading or embedding

Windows Task Scheduler (monthly, 2am on the 1st):
    Action   : Start a program
    Program  : C:\\Users\\DELL\\intuixion_collector\\venv\\Scripts\\python.exe
    Arguments: C:\\Users\\DELL\\intuixion_collector\\refresh.py
    Start in : C:\\Users\\DELL\\intuixion_collector

Environment (.env):
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...   (optional, for eval after refresh)
    QDRANT_URL=http://localhost:6333
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
LOG_PATH = PROJECT_ROOT / "data" / "refresh.log"


def run(cmd: list[str], label: str) -> tuple[int, str]:
    """Run a subprocess command, stream output, return (exit_code, summary)."""
    print(f"\n[{label}] Running: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = round(time.time() - t0, 1)
    # Print output
    for line in (proc.stdout + proc.stderr).splitlines():
        print(f"  {line}")
    summary = f"exit={proc.returncode}  elapsed={elapsed}s"
    print(f"[{label}] Done. {summary}")
    return proc.returncode, summary


def main() -> None:
    p = argparse.ArgumentParser(description="Monthly corpus refresh pipeline")
    p.add_argument("--sector", choices=["all", "healthcare", "financial", "retail", "cross"],
                   default="all")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-eval", action="store_true", help="Skip evaluation after ingest")
    args = p.parse_args()

    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    started_at = datetime.now().isoformat()
    log_entries = [{"started_at": started_at, "sector": args.sector}]

    print(f"intuixion.ai Corpus Refresh — {started_at}")
    print(f"  Sector  : {args.sector}")
    print(f"  Dry-run : {args.dry_run}")

    # ── Step 1: Collect new documents ──────────────────────────────────────
    collect_cmd = [python, "collect_sources.py", "--sector", args.sector]
    code, summary = run(collect_cmd, "COLLECT")
    log_entries.append({"step": "collect", "summary": summary, "exit": code})
    if code != 0:
        print("[ERROR] Collection failed — aborting refresh.")
        _write_log(log_entries)
        sys.exit(1)

    # ── Step 2: Ingest new files ────────────────────────────────────────────
    ingest_cmd = [python, "ingest.py", "--sector", args.sector]
    if args.dry_run:
        ingest_cmd.append("--dry-run")
    code, summary = run(ingest_cmd, "INGEST")
    log_entries.append({"step": "ingest", "summary": summary, "exit": code})
    if code != 0:
        print("[ERROR] Ingest failed.")
        _write_log(log_entries)
        sys.exit(1)

    # ── Step 3: Evaluation (optional) ──────────────────────────────────────
    if not args.skip_eval and os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        eval_cmd = [
            python, "eval.py",
            "--sector", args.sector if args.sector != "all" else "cross",
            "--retrieval-only",
        ]
        code, summary = run(eval_cmd, "EVAL")
        log_entries.append({"step": "eval", "summary": summary, "exit": code})

        # Load and surface recall metric
        results_path = PROJECT_ROOT / "data" / "eval_results.json"
        if results_path.exists():
            with open(results_path, encoding="utf-8") as f:
                report = json.load(f)
            total = report.get("total", 0)
            hits = report.get("retrieval_hits", 0)
            recall = hits / total if total else 0
            print(f"\n  Retrieval recall: {hits}/{total} ({recall:.0%})")
            log_entries.append({"retrieval_recall": recall})
    else:
        print("\n[EVAL] Skipped.")

    # ── Done ────────────────────────────────────────────────────────────────
    finished_at = datetime.now().isoformat()
    log_entries.append({"finished_at": finished_at})
    _write_log(log_entries)
    print(f"\nRefresh complete. Log written to {LOG_PATH}")


def _write_log(entries: list) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    existing = []
    if LOG_PATH.exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = []
    existing.append(entries)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


if __name__ == "__main__":
    main()
