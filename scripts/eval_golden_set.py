"""
Phase 0 golden-set evaluator (tech direction Section 3).

Runs each golden query against the live /v1/query API and checks that every
required ground appears in the generated answer.

Exits non-zero if any entry fails -- intended as a CI gate that blocks
any corpus or prompt change that regresses grounding accuracy.

Usage:
    python scripts/eval_golden_set.py
    python scripts/eval_golden_set.py --api http://localhost:8000
    python scripts/eval_golden_set.py --verbose
    python scripts/eval_golden_set.py --id popia_s11_grounds   # run one entry

Policy: any production answer confirmed as a real grounding failure gets
added to golden_set.json as a new entry before the fix is considered done.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests not installed -- pip install requests")

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"


def load_golden_set(entry_id: str | None = None) -> list[dict]:
    with open(GOLDEN_SET_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    if entry_id:
        entries = [e for e in entries if e["id"] == entry_id]
        if not entries:
            sys.exit(f"No entry with id={entry_id!r}")
    return entries


def query_api(api_url: str, question: str, timeout: int = 30, keyword_hint: str | None = None) -> dict:
    payload: dict = {"question": question, "top_k": 12}
    if keyword_hint:
        payload["keyword_hint"] = keyword_hint
    # The API requires a bearer token; scripts use the SERVICE_API_KEY (see auth.py)
    token = os.getenv("INTUIXION_API_TOKEN") or os.getenv("SERVICE_API_KEY", "")
    if not token:
        sys.exit("Set INTUIXION_API_TOKEN (or SERVICE_API_KEY) to call the API.")
    resp = requests.post(
        f"{api_url}/v1/query",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def check_entry(entry: dict, result: dict, verbose: bool) -> tuple[bool, list[str]]:
    answer = result.get("answer", "").lower()
    missing = []
    for ground in entry["required_grounds"]:
        if ground.lower() not in answer:
            missing.append(ground)
    passed = len(missing) == 0
    if verbose or not passed:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {entry['id']}  ({entry['statute_ref']})")
        if not passed:
            print(f"         Missing grounds: {missing}")
            if verbose:
                print(f"         Answer snippet: {result['answer'][:300]}...")
            print(f"         validation_status: {result.get('validation_status', 'n/a')}")
            print(f"         confidence_tier:   {result.get('confidence_tier', 'n/a')}")
    return passed, missing


def main() -> None:
    p = argparse.ArgumentParser(description="intuixion golden-set evaluator")
    p.add_argument("--api", default="http://localhost:8000", help="API base URL")
    p.add_argument("--id", dest="entry_id", help="Run a single entry by id")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()

    entries = load_golden_set(args.entry_id)
    print(f"\nintuixion golden-set eval -- {len(entries)} entr{'y' if len(entries)==1 else 'ies'}")
    print(f"API: {args.api}\n{'-' * 60}")

    results = []
    for entry in entries:
        if args.verbose:
            print(f"\nQuerying: {entry['query'][:80]}...")
        try:
            t0 = time.time()
            api_result = query_api(args.api, entry["query"], args.timeout, entry.get("keyword_hint"))
            elapsed = time.time() - t0
            passed, missing = check_entry(entry, api_result, args.verbose)
            results.append({
                "id": entry["id"],
                "passed": passed,
                "missing": missing,
                "elapsed_s": round(elapsed, 2),
                "validation_status": api_result.get("validation_status", "n/a"),
                "confidence_tier": api_result.get("confidence_tier", "n/a"),
            })
        except Exception as exc:
            print(f"  [ERROR] {entry['id']}: {exc}")
            results.append({"id": entry["id"], "passed": False, "error": str(exc)})

    # Summary
    passed_count = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print(f"\n{'-' * 60}")
    print(f"Result: {passed_count}/{total} passed")
    failed = [r for r in results if not r.get("passed")]
    if failed:
        print("\nFailed entries:")
        for r in failed:
            if "error" in r:
                print(f"  {r['id']}: ERROR -- {r['error']}")
            else:
                print(f"  {r['id']}: missing {r['missing']}")
        print(
            "\nNext step: add confirmed failures to golden_set.json as new entries "
            "and fix the prompt/corpus before re-running."
        )
        sys.exit(1)
    else:
        print("All entries grounded. ✓")


if __name__ == "__main__":
    main()
