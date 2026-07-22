"""
intuixion.ai — SA RAG Ingestion Pipeline

Reads data/manifest.json, parses each collected PDF, chunks by section,
embeds with OpenAI, and upserts to Qdrant (in-memory or remote).

Install:
    pip install pdfplumber openai qdrant-client langchain-text-splitters python-dotenv tqdm

Environment (.env or shell):
    OPENAI_API_KEY=sk-...
    EMBEDDING_MODEL=text-embedding-3-small    # or text-embedding-3-large
    COLLECTION_NAME=intuixion_sa_docs
    QDRANT_URL=http://localhost:6333          # omit for in-memory (dev only)
    QDRANT_API_KEY=...                        # Qdrant Cloud only

Usage:
    python ingest.py                          # ingest all sectors
    python ingest.py --sector healthcare      # one sector
    python ingest.py --dry-run                # parse + chunk, skip embed/upsert
    python ingest.py --limit 5               # test with 5 files
    python ingest.py --reset                  # clear state, re-ingest everything
"""

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import pdfplumber
try:
    import fitz  # pymupdf — fallback parser for scanned/non-standard PDFs
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tqdm import tqdm

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "intuixion_sa_docs")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

MANIFEST_PATH = Path("data/manifest.json")
STATE_PATH = Path("data/ingest_state.json")
PROJECT_ROOT = Path(__file__).parent

# Quality thresholds
MIN_CHUNK_WORDS = 40          # discard chunks shorter than this
ALPHA_RATIO_MIN = 0.45        # discard chunks that are mostly non-alpha (OCR garbage)
SCANNED_TEXT_THRESHOLD = 50   # chars/page below which we warn of likely scan

# Per-slug overrides for MIN_CHUNK_WORDS.
# SAMA SAMAREC SOPs are structured forms with many short paragraphs — standard
# threshold rejects >90% of their content.
SLUG_MIN_CHUNK_WORDS: dict[str, int] = {
    "sama_ethical_guidelines": 15,
}

# Files to skip at ingestion time regardless of source slug.
# Populated with non-regulatory docs scraped incidentally.
FILENAME_BLOCKLIST: set[str] = {
    # Non-regulatory content scraped incidentally
    "jse_listings_requirements__JSE_20Contact_20List_202025_0.pdf",          # contact list, not listings rules
    "fsca_regulations__FSCA_20Language_20Policy_20-_202024.pdf",             # internal admin doc
    "fsca_regulations__FSCA_20Three-Year_20Rolling_20Financial_20Education_20Plan_202025-2028.pdf",
    "bbbee_codes_good_practice__Privacy-Policy.pdf",                         # website privacy policy
    "bbbee_codes_good_practice__FRSC-Rules_Procedure.pdf",                   # procedural rules, not BEE codes
    # Confirmed image-only scans — zero text from both pdfplumber and pymupdf.
    # Require Tesseract OCR to recover. Add to a separate OCR pipeline if needed.
    "fsca_regulations__UB_20Manual.pdf",
    "icd10_coding_guidelines_sa__Notice_-additional-emergency-ICD10-codes_COVID-19.pdf",
    "icd10_coding_guidelines_sa__icd-10dictionaryicircularno03of2014.pdf",
    "icd10_coding_guidelines_sa__icd-10codescircularno06of2014.pdf",
    "icd10_coding_guidelines_sa__icd-10circularno04of2014.pdf",
    "icd10_coding_guidelines_sa__icd-10circularno05of2014.pdf",
    "icd10_coding_guidelines_sa__NoticetoallStakeholdersErrataICD-10.pdf",
    "icd10_coding_guidelines_sa__ICD-10-Circular-2-of-2014-Submission-of-Aggregated-ICD-10-Compliance-Data-2014.pdf",
    "icd10_coding_guidelines_sa__ICD-10-Phase3and41.pdf",
}

# API behaviour
EMBED_BATCH_SIZE = 50
RATE_LIMIT_DELAY = 0.3        # seconds between embedding API batches

# Fallbacks when manifest omits values
DEFAULT_CHUNK_SIZE = 1024
DEFAULT_CHUNK_OVERLAP = 200


# ---------------------------------------------------------------------------
# Ingest state — tracks sha256s already in the vector store
# ---------------------------------------------------------------------------
class IngestState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    def is_ingested(self, sha256: str) -> bool:
        return sha256 in self.data

    def mark(self, sha256: str, metadata: dict) -> None:
        self.data[sha256] = metadata
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def reset(self) -> None:
        self.data = {}
        if self.path.exists():
            self.path.unlink()


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------
def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _fitz_page_text(pdf_path: Path, page_index: int) -> str:
    """Extract text from a single page using pymupdf (fallback parser)."""
    if not PYMUPDF_AVAILABLE:
        return ""
    try:
        doc = fitz.open(str(pdf_path))
        text = doc[page_index].get_text()
        doc.close()
        return text or ""
    except Exception:
        return ""


def extract_pages(pdf_path: Path) -> tuple[list[dict], list[str]]:
    """
    Open a PDF and return (pages, warnings).
    Each page dict: {"page": int, "text": str, "tables": list[list[list]]}

    If pdfplumber returns no text for a page, pymupdf is tried as a fallback.
    This recovers text from non-standard PDFs that pdfplumber cannot parse.
    True image-only scans will still return empty — those require Tesseract OCR.
    """
    pages: list[dict] = []
    warnings: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []

            # Fallback: try pymupdf if pdfplumber found nothing
            if not text.strip() and not tables and PYMUPDF_AVAILABLE:
                text = _fitz_page_text(pdf_path, i - 1)
                if text.strip():
                    warnings.append(f"page {i}: used pymupdf fallback parser")

            if len(text.strip()) < SCANNED_TEXT_THRESHOLD and not tables:
                warnings.append(f"page {i} may be scanned/unrecoverable")

            pages.append({"page": i, "text": text, "tables": tables})
    return pages, warnings


def format_table_markdown(table: list[list]) -> str:
    """Convert a pdfplumber table (list of rows) to a markdown table string."""
    if not table:
        return ""
    rows = [[str(cell or "").strip().replace("\n", " ") for cell in row] for row in table]
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    width = len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in body:
        # Pad short rows to header width
        row = (row + [""] * width)[:width]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def pages_to_text(pages: list[dict], unstructured_mode: str) -> str:
    """
    Combine all page content into one string.
    'table' mode: render tables as markdown, interleaved with prose.
    'by_title' mode: plain text join.
    """
    parts: list[str] = []
    for p in pages:
        text = p["text"].strip()
        if unstructured_mode == "table":
            table_parts = [format_table_markdown(t) for t in p["tables"] if t]
            table_parts = [t for t in table_parts if t]
            if table_parts:
                parts.extend(table_parts)
            elif text:
                parts.append(text)
        else:
            if text:
                parts.append(text)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    unstructured_mode: str,
) -> list[str]:
    """
    Split text into chunks.
    'table' mode: each non-divider markdown table row is its own chunk.
    'by_title' mode: recursive character split respecting paragraph boundaries.
    """
    if unstructured_mode == "table":
        row_re = re.compile(r"^\|.+\|$")
        divider_re = re.compile(r"^\|[-| ]+\|$")
        chunks = []
        for line in text.splitlines():
            line = line.strip()
            if row_re.match(line) and not divider_re.match(line):
                chunks.append(line)
        return chunks or [text]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    return splitter.split_text(text)


# ---------------------------------------------------------------------------
# Quality filter
# ---------------------------------------------------------------------------
def is_quality_chunk(text: str, min_words: int = MIN_CHUNK_WORDS) -> bool:
    if len(text.split()) < min_words:
        return False
    alpha = sum(1 for c in text if c.isalpha())
    if len(text) > 0 and (alpha / len(text)) < ALPHA_RATIO_MIN:
        return False
    return True


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        # API rejects empty strings and null bytes
        batch = [t.replace("\x00", " ").strip() or " " for t in batch]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend([r.embedding for r in response.data])
        if i + EMBED_BATCH_SIZE < len(texts):
            time.sleep(RATE_LIMIT_DELAY)
    return embeddings


# ---------------------------------------------------------------------------
# Vector store helpers
# ---------------------------------------------------------------------------
def get_qdrant(url: Optional[str], api_key: Optional[str]) -> QdrantClient:
    if url:
        return QdrantClient(url=url, api_key=api_key)
    return QdrantClient(":memory:")


def ensure_collection(qdrant: QdrantClient, name: str, dim: int) -> None:
    existing = {c.name for c in qdrant.get_collections().collections}
    if name not in existing:
        qdrant.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        print(f"  Created Qdrant collection '{name}' (dim={dim}, distance=cosine)")


def make_point_id(sha256: str, chunk_idx: int) -> str:
    # Deterministic UUID — re-running produces the same IDs (safe upsert)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sha256}:{chunk_idx}"))


def upsert_chunks(
    qdrant: QdrantClient,
    collection: str,
    chunks: list[str],
    embeddings: list[list[float]],
    base_payload: dict,
) -> int:
    points = [
        PointStruct(
            id=make_point_id(base_payload["sha256"], idx),
            vector=vec,
            payload={
                **base_payload,
                "text": chunk,
                "chunk_idx": idx,
                "chunk_count": len(chunks),
            },
        )
        for idx, (chunk, vec) in enumerate(zip(chunks, embeddings))
    ]
    qdrant.upsert(collection_name=collection, points=points)
    return len(points)


# ---------------------------------------------------------------------------
# Per-file pipeline
# ---------------------------------------------------------------------------
def ingest_file(
    pdf_path: Path,
    source_meta: dict,
    sha256: str,
    oai_client: Optional[OpenAI],
    qdrant: Optional[QdrantClient],
    collection: str,
    state: IngestState,
    dry_run: bool,
) -> dict:
    chunk_size = source_meta.get("chunk_size") or DEFAULT_CHUNK_SIZE
    chunk_overlap = source_meta.get("chunk_overlap") or DEFAULT_CHUNK_OVERLAP
    unstructured_mode = source_meta.get("unstructured_mode") or "by_title"

    # 1. Parse
    try:
        pages, warnings = extract_pages(pdf_path)
    except Exception as exc:
        return {"status": "error", "reason": f"PDF parse failed: {exc}"}

    for w in warnings[:3]:
        tqdm.write(f"    [WARN] {w}")

    full_text = pages_to_text(pages, unstructured_mode)
    if not full_text.strip():
        return {"status": "skip", "reason": "no extractable text"}

    # 2. Chunk
    min_words = SLUG_MIN_CHUNK_WORDS.get(source_meta.get("slug", ""), MIN_CHUNK_WORDS)
    raw_chunks = chunk_text(full_text, chunk_size, chunk_overlap, unstructured_mode)
    chunks = [c for c in raw_chunks if is_quality_chunk(c, min_words)]
    if not chunks:
        return {"status": "skip", "reason": "all chunks failed quality filter"}

    if dry_run:
        tqdm.write(f"    [DRY-RUN] {len(chunks)} chunks (from {len(raw_chunks)} raw)")
        return {"status": "dry_run", "chunks": len(chunks)}

    # 3. Embed
    try:
        embeddings = embed_batch(oai_client, chunks)
    except Exception as exc:
        return {"status": "error", "reason": f"embedding failed: {exc}"}

    # 4. Upsert
    base_payload = {
        "slug": source_meta["slug"],
        "name": source_meta["name"],
        "sector": source_meta["sector"],
        "file": pdf_path.name,
        "source_url": source_meta.get("index_url", ""),
        "sha256": sha256,
        "page_count": len(pages),
        "unstructured_mode": unstructured_mode,
        "ingested_at": time.strftime("%Y-%m-%d"),
    }
    try:
        n = upsert_chunks(qdrant, collection, chunks, embeddings, base_payload)
    except Exception as exc:
        return {"status": "error", "reason": f"upsert failed: {exc}"}

    state.mark(sha256, {
        "slug": source_meta["slug"],
        "file": pdf_path.name,
        "chunks": n,
        "ingested_at": base_payload["ingested_at"],
    })
    return {"status": "ok", "chunks": n}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="intuixion.ai SA RAG Ingestion Pipeline")
    p.add_argument(
        "--sector",
        choices=["all", "healthcare", "financial", "retail", "cross"],
        default=os.getenv("INGEST_SECTOR", "all"),
    )
    p.add_argument("--reset", action="store_true", help="Clear ingest state; re-process all files")
    p.add_argument("--dry-run", action="store_true", help="Parse and chunk only — no embed/upsert")
    p.add_argument("--limit", type=int, default=0, metavar="N", help="Process at most N files (0 = all)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    state = IngestState(STATE_PATH)
    if args.reset:
        print("Resetting ingest state — all files will be re-processed.")
        state.reset()

    if not args.dry_run:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY is required. Set it in .env or the shell.")
        oai_client = OpenAI(api_key=api_key)
        dim = EMBEDDING_DIMS.get(EMBEDDING_MODEL, 1536)
        qdrant = get_qdrant(QDRANT_URL, QDRANT_API_KEY)
        ensure_collection(qdrant, COLLECTION_NAME, dim)
    else:
        oai_client = None
        qdrant = None

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest: list[dict] = json.load(f)

    if args.sector != "all":
        manifest = [m for m in manifest if m.get("sector") == args.sector]

    # Flatten manifest → list of (source_meta, pdf_path)
    work: list[tuple[dict, Path]] = []
    for source in manifest:
        for file_str in source.get("files", []):
            pdf_path = PROJECT_ROOT / file_str
            if pdf_path.exists():
                work.append((source, pdf_path))

    if args.limit:
        work = work[: args.limit]

    print(f"\nintuixion.ai Ingestion Pipeline")
    print(f"  Mode       : {'dry-run' if args.dry_run else 'live'}")
    print(f"  Sector     : {args.sector}")
    print(f"  Files      : {len(work)}")
    if not args.dry_run:
        print(f"  Model      : {EMBEDDING_MODEL}")
        print(f"  Store      : {QDRANT_URL or 'in-memory (not persistent)'}")
        print(f"  Collection : {COLLECTION_NAME}")
    print()

    total_chunks = 0
    n_ok = 0
    n_skip = 0
    n_err = 0
    seen_this_run: set[str] = set()  # sha256 dedup within a single run

    for source_meta, pdf_path in tqdm(work, desc="Files", unit="file"):
        # Fix 4: skip known non-regulatory files scraped incidentally
        if pdf_path.name in FILENAME_BLOCKLIST:
            tqdm.write(f"  [SKIP] {pdf_path.name} (blocklisted)")
            n_skip += 1
            continue

        sha256 = file_sha256(pdf_path)

        # Fix 1: cross-slug dedup — EML and STG download identical files
        if sha256 in seen_this_run:
            tqdm.write(f"  [SKIP] {pdf_path.name} (duplicate content already ingested)")
            n_skip += 1
            continue
        seen_this_run.add(sha256)

        if state.is_ingested(sha256) and not args.reset:
            tqdm.write(f"  [SKIP] {pdf_path.name}")
            n_skip += 1
            continue

        tqdm.write(f"  [PROC] {pdf_path.name}")
        result = ingest_file(
            pdf_path=pdf_path,
            source_meta=source_meta,
            sha256=sha256,
            oai_client=oai_client,
            qdrant=qdrant,
            collection=COLLECTION_NAME,
            state=state,
            dry_run=args.dry_run,
        )

        status = result["status"]
        if status in ("ok", "dry_run"):
            n = result.get("chunks", 0)
            tqdm.write(f"    -> {n} chunks {'(would ingest)' if args.dry_run else 'ingested'}")
            total_chunks += n
            n_ok += 1
        elif status == "skip":
            tqdm.write(f"    [SKIP] {result['reason']}")
            n_skip += 1
        else:
            tqdm.write(f"    [ERROR] {result['reason']}")
            n_err += 1

    print(f"\n{'=' * 60}")
    print(f"Done.")
    print(f"  Processed : {n_ok}")
    print(f"  Chunks    : {total_chunks}")
    print(f"  Skipped   : {n_skip}  (already ingested)")
    print(f"  Errors    : {n_err}")
    if not args.dry_run and not QDRANT_URL:
        print()
        print("  NOTE: in-memory Qdrant is active — vectors are not persisted.")
        print("  Set QDRANT_URL=http://localhost:6333 to persist across runs.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
