"""
Migrate Qdrant corpus to Fly.io via S3 af-south-1 relay.

  1. Upload snapshot to S3 af-south-1  (Windows → S3 JNB, fast local)
  2. Generate 4-hour pre-signed URL
  3. Trigger Fly Qdrant to pull from that URL  (S3 JNB → Fly JNB, ~instant)
  4. Poll until green, verify point count

IAM requirement: intuixion-bedrock user needs the S3MigrationPolicy
(see setup instructions below).

Usage:
    python scripts/migrate_qdrant_snapshot.py
"""

import os
import pathlib
import sys
import time

import requests
import boto3
import boto3.s3.transfer
from dotenv import load_dotenv

load_dotenv()

SNAPSHOT_PATH = pathlib.Path(
    "qdrant/snapshots/intuixion_sa_docs/"
    "intuixion_sa_docs-3482183114550295-2026-09-27-04-06-22.snapshot"
)
FLY_QDRANT_URL = "https://intx-qdrant.fly.dev"
COLLECTION = "intuixion_sa_docs"
BUCKET = "intuixion-qdrant-migration"
REGION = os.getenv("AWS_REGION", "af-south-1")
S3_KEY = f"snapshots/{SNAPSHOT_PATH.name}"
EXPECTED_POINTS = 18289
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "NnPVCwdz17Upj9b9drbNYMLhCMQZ6XxS01bw/pe6kYE=")
_QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}


def _s3():
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def ensure_bucket(s3):
    try:
        s3.head_bucket(Bucket=BUCKET)
        print(f"  bucket {BUCKET} already exists")
    except Exception:
        print(f"  creating bucket {BUCKET} in {REGION}...")
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_public_access_block(
            Bucket=BUCKET,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        print("  bucket created (private)")


def upload_snapshot(s3):
    size_mb = SNAPSHOT_PATH.stat().st_size / 1_048_576
    print(f"  uploading {size_mb:.0f} MB to s3://{BUCKET}/{S3_KEY} ...")

    class _Progress:
        def __init__(self, total):
            self._total = total
            self._seen = 0
            self._t0 = time.time()

        def __call__(self, n):
            self._seen += n
            pct = self._seen / self._total * 100
            elapsed = time.time() - self._t0
            rate = (self._seen / 1_048_576) / max(elapsed, 0.1)
            bar = "#" * int(pct / 2)
            print(f"\r  [{bar:<50}] {pct:.1f}%  {rate:.1f} MB/s", end="", flush=True)

    config = boto3.s3.transfer.TransferConfig(
        multipart_threshold=32 * 1024 * 1024,
        max_concurrency=8,
        multipart_chunksize=32 * 1024 * 1024,
    )
    s3.upload_file(
        str(SNAPSHOT_PATH),
        BUCKET,
        S3_KEY,
        Config=config,
        Callback=_Progress(SNAPSHOT_PATH.stat().st_size),
    )
    print()


def presign(s3) -> str:
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": S3_KEY},
        ExpiresIn=4 * 3600,
    )
    print("  pre-signed URL generated (4h expiry)")
    return url


def trigger_recovery(url: str):
    print("  triggering Fly Qdrant recovery from S3...")
    resp = requests.put(
        f"{FLY_QDRANT_URL}/collections/{COLLECTION}/snapshots/recover",
        json={"location": url, "priority": "snapshot"},
        headers={**_QDRANT_HEADERS, "Content-Type": "application/json"},
        timeout=30,
    )
    if not resp.ok:
        print(f"  ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    print(f"  recovery started: {resp.json()}")


def wait_for_recovery(timeout: int = 600):
    print(f"  waiting for {EXPECTED_POINTS} points to index...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{FLY_QDRANT_URL}/collections/{COLLECTION}",
                             headers=_QDRANT_HEADERS, timeout=10)
            if r.status_code == 200:
                info = r.json().get("result", {})
                status = info.get("status")
                count = info.get("points_count", 0)
                print(f"\r  status={status}  points={count}   ", end="", flush=True)
                if status == "green" and count >= EXPECTED_POINTS * 0.95:
                    print(f"\n  done: {count} points")
                    return count
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError("Collection not green after timeout")


def cleanup(s3):
    print(f"  deleting s3://{BUCKET}/{S3_KEY} ...")
    s3.delete_object(Bucket=BUCKET, Key=S3_KEY)
    s3.delete_bucket(Bucket=BUCKET)
    print("  migration bucket deleted")


def main():
    if not SNAPSHOT_PATH.exists():
        sys.exit(f"Snapshot not found: {SNAPSHOT_PATH}\nRun from project root.")

    s3 = _s3()

    print("\n=== Step 1: S3 bucket ===")
    ensure_bucket(s3)

    print("\n=== Step 2: Upload to S3 af-south-1 ===")
    upload_snapshot(s3)

    print("\n=== Step 3: Pre-signed URL ===")
    url = presign(s3)

    print("\n=== Step 4: Trigger Fly Qdrant recovery ===")
    trigger_recovery(url)

    print("\n=== Step 5: Wait for indexing ===")
    count = wait_for_recovery()

    print("\n=== Step 6: Cleanup S3 ===")
    cleanup(s3)

    print(f"\n=== Migration complete: {count} points ===")
    print(f"    {FLY_QDRANT_URL}/collections/{COLLECTION}")


if __name__ == "__main__":
    main()
