"""Quick quality analysis of ingestion corpus — run with venv python."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import json
from pathlib import Path

import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter

PROJECT_ROOT = Path(__file__).parent
MANIFEST = PROJECT_ROOT / "data/manifest.json"
MIN_CHUNK_WORDS = 40
ALPHA_RATIO_MIN = 0.45
SCANNED_THRESHOLD = 50

with open(MANIFEST, encoding="utf-8") as f:
    manifest = json.load(f)


def is_quality(text: str) -> bool:
    if len(text.split()) < MIN_CHUNK_WORDS:
        return False
    alpha = sum(1 for c in text if c.isalpha())
    return len(text) == 0 or (alpha / len(text)) >= ALPHA_RATIO_MIN


results = []
errors = []

for source in manifest:
    for file_str in source.get("files", []):
        pdf_path = PROJECT_ROOT / file_str
        if not pdf_path.exists():
            continue
        chunk_size = source.get("chunk_size") or 1024
        chunk_overlap = source.get("chunk_overlap") or 200
        mode = source.get("unstructured_mode") or "by_title"
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = []
                scanned_pages = 0
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    if len(text.strip()) < SCANNED_THRESHOLD:
                        scanned_pages += 1
                    pages_text.append(text)
            full_text = "\n\n".join(p for p in pages_text if p.strip())
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
                length_function=len,
            )
            raw = splitter.split_text(full_text) if full_text.strip() else []
            good = [c for c in raw if is_quality(c)]
            results.append({
                "slug": source["slug"],
                "sector": source["sector"],
                "file": pdf_path.name,
                "pages": len(pages_text),
                "scanned_pages": scanned_pages,
                "raw_chunks": len(raw),
                "good_chunks": len(good),
                "filtered": len(raw) - len(good),
                "filter_pct": round((len(raw) - len(good)) / max(len(raw), 1) * 100, 1),
                "mode": mode,
                "chars": len(full_text),
                "has_text": bool(full_text.strip()),
            })
            print(f"  OK  {len(good):>5} chunks  {pdf_path.name[:60]}")
        except Exception as exc:
            errors.append({"file": pdf_path.name, "slug": source["slug"], "error": str(exc)})
            print(f"  ERR {pdf_path.name[:60]} — {exc}")

# ── Derived stats ──────────────────────────────────────────────────────────
total_files = len(results)
total_raw = sum(r["raw_chunks"] for r in results)
total_good = sum(r["good_chunks"] for r in results)
total_filtered = sum(r["filtered"] for r in results)
total_pages = sum(r["pages"] for r in results)
total_scanned = sum(r["scanned_pages"] for r in results)
total_chars = sum(r["chars"] for r in results)

no_text = [r for r in results if not r["has_text"]]
zero_good = [r for r in results if r["good_chunks"] == 0 and r["raw_chunks"] > 0]
high_filter = [r for r in results if r["filter_pct"] > 30 and r["raw_chunks"] > 5]
mostly_scanned = [r for r in results if r["scanned_pages"] > r["pages"] * 0.5 and r["pages"] > 1]

sep = "=" * 62
print(f"\n{sep}")
print("INGESTION QUALITY ANALYSIS")
print(sep)

print(f"\n── Corpus overview ───────────────────────────────────────")
print(f"  Files analysed       : {total_files}")
print(f"  Total pages          : {total_pages:,}")
print(f"  Scanned/low-text pgs : {total_scanned:,}  ({total_scanned/max(total_pages,1)*100:.1f}%)")
print(f"  Total characters     : {total_chars:,}")

print(f"\n── Chunking ──────────────────────────────────────────────")
print(f"  Raw chunks           : {total_raw:,}")
print(f"  After quality filter : {total_good:,}  ({total_good/max(total_raw,1)*100:.1f}% kept)")
print(f"  Filtered out         : {total_filtered:,}  ({total_filtered/max(total_raw,1)*100:.1f}%)")
print(f"  Avg chunks / file    : {total_good/max(total_files,1):.0f}")

print(f"\n── By sector ─────────────────────────────────────────────")
sectors: dict = {}
for r in results:
    s = r["sector"]
    sectors.setdefault(s, {"files": 0, "chunks": 0, "scanned": 0, "pages": 0})
    sectors[s]["files"] += 1
    sectors[s]["chunks"] += r["good_chunks"]
    sectors[s]["scanned"] += r["scanned_pages"]
    sectors[s]["pages"] += r["pages"]
for s, v in sorted(sectors.items()):
    scan_pct = v["scanned"] / max(v["pages"], 1) * 100
    print(f"  {s:<12} {v['files']:>3} files   {v['chunks']:>6,} chunks   {scan_pct:.0f}% scanned pages")

print(f"\n── Quality concerns ──────────────────────────────────────")
any_concern = False

if no_text:
    any_concern = True
    print(f"  [CRITICAL] {len(no_text)} file(s) produced NO extractable text:")
    for r in no_text:
        print(f"             {r['file']}")

if zero_good:
    any_concern = True
    print(f"  [CRITICAL] {len(zero_good)} file(s): raw chunks exist but ALL filtered:")
    for r in zero_good:
        print(f"             {r['file']}  (filter={r['filter_pct']}%)")

if mostly_scanned:
    any_concern = True
    print(f"  [WARNING]  {len(mostly_scanned)} file(s) are >50% scanned — OCR may be needed:")
    for r in mostly_scanned:
        print(f"             {r['scanned_pages']}/{r['pages']} pages scanned — {r['file'][:55]}")

if high_filter:
    any_concern = True
    print(f"  [WARNING]  {len(high_filter)} file(s) with >30% chunks filtered (OCR noise likely):")
    for r in sorted(high_filter, key=lambda x: -x["filter_pct"]):
        print(f"             {r['filter_pct']:>5.1f}% filtered — {r['file'][:52]}")

if errors:
    any_concern = True
    print(f"  [ERROR]    {len(errors)} file(s) failed to parse:")
    for e in errors:
        print(f"             {e['file']}: {e['error'][:60]}")

if not any_concern:
    print("  No quality concerns — corpus looks clean.")

print(f"\n── Top 10 files by chunk count ───────────────────────────")
for r in sorted(results, key=lambda x: -x["good_chunks"])[:10]:
    print(f"  {r['good_chunks']:>5}  {r['file'][:56]}")

print(f"\n── Bottom 10 files by chunk count (non-zero) ────────────")
for r in sorted([r for r in results if r["good_chunks"] > 0], key=lambda x: x["good_chunks"])[:10]:
    print(f"  {r['good_chunks']:>5}  {r['file'][:56]}")

print(f"\n── Estimated embedding cost ──────────────────────────────")
est_tokens = total_good * 300
cost_small = est_tokens / 1_000_000 * 0.020
cost_large = est_tokens / 1_000_000 * 0.130
print(f"  Chunks to embed          : {total_good:,}")
print(f"  Estimated tokens (~300/chunk) : ~{est_tokens/1_000_000:.1f}M")
print(f"  text-embedding-3-small   : ~${cost_small:.2f}")
print(f"  text-embedding-3-large   : ~${cost_large:.2f}")

print(f"\n{sep}")
