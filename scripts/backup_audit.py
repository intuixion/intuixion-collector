"""
Daily audit log backup (tech direction constraint 5 — backups are baseline).

Copies data/audit.db to a timestamped file. Run daily via Task Scheduler (Windows)
or cron (Linux/Mac). For off-site backup, pipe to rclone or an S3 CLI after copy.

Usage:
    python scripts/backup_audit.py                  # copy to data/backups/
    python scripts/backup_audit.py --dest /mnt/nas  # custom destination
    python scripts/backup_audit.py --s3 s3://bucket/intuixion/backups/  # S3 (needs aws cli)

Retention: keeps 30 daily copies by default; deletes older ones automatically.
"""

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"
DEFAULT_BACKUP_DIR = Path(__file__).parent.parent / "data" / "backups"
RETENTION_DAYS = 30


def backup_local(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"audit_{stamp}.db"
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest))
    with dst:
        src.backup(dst)  # safe online backup — consistent snapshot even under writes
    src.close()
    dst.close()
    return dest


def prune_old(dest_dir: Path, retention: int) -> list[Path]:
    cutoff = datetime.utcnow() - timedelta(days=retention)
    removed = []
    for f in sorted(dest_dir.glob("audit_*.db")):
        try:
            ts = datetime.strptime(f.stem.replace("audit_", ""), "%Y%m%d_%H%M%S")
            if ts < cutoff:
                f.unlink()
                removed.append(f)
        except ValueError:
            pass
    return removed


def backup_s3(local: Path, s3_prefix: str) -> None:
    dest = s3_prefix.rstrip("/") + "/" + local.name
    result = subprocess.run(
        ["aws", "s3", "cp", str(local), dest],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"S3 upload failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"Uploaded to {dest}")


def main():
    p = argparse.ArgumentParser(description="Backup intuixion audit.db")
    p.add_argument("--dest", default=str(DEFAULT_BACKUP_DIR), help="Local backup directory")
    p.add_argument("--s3", default="", help="S3 prefix for off-site copy (requires aws cli)")
    p.add_argument("--retention", type=int, default=RETENTION_DAYS, help="Days of backups to keep")
    args = p.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH} — nothing to back up.", file=sys.stderr)
        sys.exit(0)

    dest_dir = Path(args.dest)
    backup_file = backup_local(dest_dir)
    print(f"Backed up to {backup_file}  ({backup_file.stat().st_size:,} bytes)")

    removed = prune_old(dest_dir, args.retention)
    if removed:
        print(f"Pruned {len(removed)} backup(s) older than {args.retention} days")

    if args.s3:
        backup_s3(backup_file, args.s3)


if __name__ == "__main__":
    main()
