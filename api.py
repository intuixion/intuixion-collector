"""
intuixion.ai — DocuRAG FastAPI Backend  v1.2.0

All endpoints are available at both root and /v1/ prefix (v1 is canonical):
    POST /v1/query       — semantic search + Claude answer (with citation validation)
    POST /v1/ingest      — upload and ingest a PDF
    GET  /v1/sources     — list ingested sources
    GET  /health         — health check (root only — used by uptime monitors)
    GET  /v1/audit/flagged  — internal review queue (flagged answers)
    GET  /v1/audit/signals  — demand-signal counts (case law, human review)
    GET  /v1/metrics     — lightweight operational metrics
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import urllib.request
import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

# Sentry error tracking — activate by setting SENTRY_DSN in .env
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=_sentry_dsn, traces_sample_rate=0.1)
    except ImportError:
        pass  # sentry_sdk not installed — skip silently

from audit.logger import init_db, log_query, flagged_review_queue, demand_signals, query_metrics
from validation.citation_parser import validate as validate_citations, repair_prompt, ValidationResult
from validation.confidence_scoring import score as confidence_score, infer_source_type
from validation.feature_flags import is_enabled
from validation.grounding_judge import judge_in_background
from validation.saflii import saflii_url as _saflii_url, noteup_url as _noteup_url

# Initialise audit DB on startup
init_db()

app = FastAPI(
    title="intuixion.ai DocuRAG API",
    description="SA Regulatory Document Intelligence",
    version="1.2.0",
)

# Versioned router — all feature endpoints live here; mounted at /v1/
v1 = APIRouter(prefix="/v1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://intuixion.ai",
        "https://demo.intuixion.ai",
        "https://app.intuixion.ai",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    sector: Optional[str] = None
    slug: Optional[str] = None
    top_k: int = Field(default=8, ge=1, le=20)


class CitationItem(BaseModel):
    slug: str
    name: str
    sector: str
    chunk_idx: int
    chunk_count: int
    score: float
    text: str
    source_url: str
    source_type: str = "guidance"
    saflii_url: Optional[str] = None
    noteup_url: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationItem]
    retrieval_ms: int
    answer_ms: int
    validation_ms: int = 0
    validation_status: str = "not_validated"   # 'grounded' | 'flagged' | 'not_validated'
    confidence_tier: str = "low"               # 'high' | 'medium' | 'low'


class IngestResponse(BaseModel):
    status: str
    filename: str
    chunks: int
    message: str


class SourceItem(BaseModel):
    slug: str
    name: str
    sector: str
    files: int
    chunks: int


# ---------------------------------------------------------------------------
# Lazy-loaded clients
# ---------------------------------------------------------------------------
_retriever = None
_agent = None


def _get_retriever():
    global _retriever
    if _retriever is None:
        from query import retrieve
        _retriever = retrieve
    return _retriever


def _get_agent():
    global _agent
    if _agent is None:
        from agent import run_agent
        _agent = run_agent
    return _agent


# ---------------------------------------------------------------------------
# Routes — health at root, all features under v1 router
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    qdrant_url = os.getenv("QDRANT_URL", "")
    if qdrant_url:
        try:
            urllib.request.urlopen(f"{qdrant_url}/healthz", timeout=2)
        except Exception:
            return JSONResponse(
                {"status": "degraded", "qdrant": "unreachable",
                 "service": "intuixion-docurag", "version": "1.2.0"},
                status_code=503,
            )
    return {"status": "ok", "qdrant": "ok" if qdrant_url else "skipped",
            "service": "intuixion-docurag", "version": "1.2.0"}


def _run_query(req: QueryRequest) -> QueryResponse:
    """Core query logic — shared by root and /v1/ endpoints."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    retrieve = _get_retriever()
    run_agent = _get_agent()

    # ── 1. Retrieve ──────────────────────────────────────────────────────────
    t0 = time.time()
    try:
        chunks = retrieve(
            query=req.question,
            top_k=req.top_k,
            sector=req.sector,
            slug=req.slug,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval failed: {exc}")
    retrieval_ms = int((time.time() - t0) * 1000)

    retrieved_slugs = {c.get("slug", "") for c in chunks if c.get("slug")}

    # ── 2. Score confidence (deterministic, before generation) ───────────────
    if is_enabled("confidence_scoring"):
        confidence_tier, source_breakdown = confidence_score(chunks)
    else:
        confidence_tier, source_breakdown = "low", {}

    # ── 3. Generate ──────────────────────────────────────────────────────────
    t1 = time.time()
    try:
        answer, _ = run_agent(
            user_message=req.question,
            history=[],
            sector_hint=req.sector,
            verbose=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent failed: {exc}")
    answer_ms = int((time.time() - t1) * 1000)

    # ── 4. Validate citations (Option A — deterministic) ─────────────────────
    t2 = time.time()
    validation = (
        validate_citations(answer, retrieved_slugs)
        if is_enabled("citation_validation")
        else ValidationResult(status="not_validated")
    )
    row_id: Optional[str] = None

    if validation.status == "flagged":
        # One synchronous retry with a targeted repair instruction
        repair_msg = repair_prompt(req.question, validation.flagged_clauses)
        try:
            t_retry = time.time()
            answer_retry, _ = run_agent(
                user_message=repair_msg,
                history=[],
                sector_hint=req.sector,
                verbose=False,
            )
            answer_ms += int((time.time() - t_retry) * 1000)
            validation_retry = validate_citations(answer_retry, retrieved_slugs)
            if validation_retry.status == "grounded":
                answer = answer_retry
                validation = validation_retry
            # Both attempts failed — Option B fires in background after logging
        except Exception:
            pass  # Keep original answer; validation_status remains 'flagged'

    validation_ms = int((time.time() - t2) * 1000)

    # ── 5. Log to audit ──────────────────────────────────────────────────────
    total_ms = retrieval_ms + answer_ms + validation_ms
    if is_enabled("audit_logging"):
        try:
            row_id = log_query(
                query_text=req.question,
                retrieved_chunk_ids=list(retrieved_slugs),
                source_type_breakdown=source_breakdown,
                generated_answer=answer,
                confidence_tier=confidence_tier,
                validation_status=validation.status,
                flagged_clauses=validation.flagged_clauses if validation.flagged_clauses else None,
                latency_ms=total_ms,
                stage_latency_ms={
                    "retrieval": retrieval_ms,
                    "generation": answer_ms,
                    "validation": validation_ms,
                },
            )
        except Exception:
            pass  # Audit failure never blocks the response

    # ── 6. Option B — async LLM judge if both Option A passes failed ─────────
    if validation.status == "flagged" and row_id and validation.flagged_clauses:
        judge_in_background(row_id, validation.flagged_clauses, chunks)

    # ── 7. Build citations list with SAFLII link-out ─────────────────────────
    citations = [
        CitationItem(
            slug=c.get("slug", ""),
            name=c.get("name", ""),
            sector=c.get("sector", ""),
            chunk_idx=c.get("chunk_idx", 0),
            chunk_count=c.get("chunk_count", 0),
            score=c.get("score", 0.0),
            text=c.get("text", "")[:500],
            source_url=c.get("source_url", ""),
            source_type=infer_source_type(c),
            saflii_url=_saflii_url(c.get("slug", "")) if is_enabled("saflii_links") else None,
            noteup_url=_noteup_url(c.get("slug", "")) if is_enabled("saflii_links") else None,
        )
        for c in chunks
    ]

    return QueryResponse(
        answer=answer,
        citations=citations,
        retrieval_ms=retrieval_ms,
        answer_ms=answer_ms,
        validation_ms=validation_ms,
        validation_status=validation.status,
        confidence_tier=confidence_tier,
    )


async def _run_ingest(file: UploadFile, sector: str) -> IngestResponse:
    """Core ingest logic — shared by root and /v1/ endpoints."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        dest = Path(tmp_dir) / file.filename
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            from ingest import (
                IngestState, extract_pages, pages_to_text, chunk_text,
                is_quality_chunk, embed_batch, upsert_chunks, file_sha256,
                get_qdrant, ensure_collection, COLLECTION_NAME, EMBEDDING_MODEL,
                EMBEDDING_DIMS, QDRANT_URL, QDRANT_API_KEY, STATE_PATH,
                DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP,
            )
            from openai import OpenAI

            sha256 = file_sha256(dest)
            pages, _ = extract_pages(dest)
            full_text = pages_to_text(pages, "by_title")
            if not full_text.strip():
                return IngestResponse(
                    status="skip", filename=file.filename, chunks=0,
                    message="No extractable text found in this PDF.",
                )

            raw_chunks = chunk_text(full_text, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP, "by_title")
            chunks_filtered = [c for c in raw_chunks if is_quality_chunk(c)]
            if not chunks_filtered:
                return IngestResponse(
                    status="skip", filename=file.filename, chunks=0,
                    message="Document content too short or low quality.",
                )

            oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            embeddings = embed_batch(oai, chunks_filtered)

            qdrant = get_qdrant(QDRANT_URL, QDRANT_API_KEY)
            dim = EMBEDDING_DIMS.get(EMBEDDING_MODEL, 1536)
            ensure_collection(qdrant, COLLECTION_NAME, dim)

            base_payload = {
                "slug": f"custom__{Path(file.filename).stem.lower()[:40]}",
                "name": file.filename,
                "sector": sector,
                "source_type": "guidance",
                "file": file.filename,
                "source_url": "",
                "sha256": sha256,
                "page_count": len(pages),
                "unstructured_mode": "by_title",
                "ingested_at": time.strftime("%Y-%m-%d"),
            }
            n = upsert_chunks(qdrant, COLLECTION_NAME, chunks_filtered, embeddings, base_payload)

            state = IngestState(STATE_PATH)
            state.mark(sha256, {
                "slug": base_payload["slug"],
                "file": file.filename,
                "chunks": n,
                "ingested_at": base_payload["ingested_at"],
            })

            return IngestResponse(
                status="ok", filename=file.filename, chunks=n,
                message=f"Successfully ingested {n} chunks.",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


def _sources_list() -> list[SourceItem]:
    """Core sources logic — shared by root and /v1/ endpoints."""
    import json as _json
    manifest_path = Path("data/manifest.json")
    if not manifest_path.exists():
        return []

    with open(manifest_path, encoding="utf-8") as f:
        manifest = _json.load(f)

    state_path = Path("data/ingest_state.json")
    state_chunks: dict[str, int] = {}
    if state_path.exists():
        with open(state_path, encoding="utf-8") as f:
            state = _json.load(f)
        for meta in state.values():
            slug = meta.get("slug", "")
            state_chunks[slug] = state_chunks.get(slug, 0) + meta.get("chunks", 0)

    result = []
    for entry in manifest:
        if not entry.get("files"):
            continue
        slug = entry["slug"]
        result.append(SourceItem(
            slug=slug,
            name=entry.get("name", slug),
            sector=entry.get("sector", ""),
            files=len(entry.get("files", [])),
            chunks=state_chunks.get(slug, 0),
        ))

    return [s for s in result if s.chunks > 0]


# ── /v1/ versioned routes (canonical) ────────────────────────────────────────

@v1.post("/query", response_model=QueryResponse)
def v1_query(req: QueryRequest):
    return _run_query(req)


@v1.post("/ingest", response_model=IngestResponse)
async def v1_ingest(file: UploadFile = File(...), sector: str = Form(default="cross")):
    return await _run_ingest(file, sector)


@v1.get("/sources", response_model=list[SourceItem])
def v1_sources():
    return _sources_list()


@v1.get("/audit/flagged")
def v1_audit_flagged(limit: int = 50):
    return flagged_review_queue(limit=limit)


@v1.get("/audit/signals")
def v1_audit_signals(days: int = 30):
    signals = demand_signals(days=days)
    return {
        **signals,
        "days": days,
        "case_law_threshold_met": signals["case_law_distinct_users"] >= 2,
        "human_review_threshold_met": signals["human_review_distinct_users"] >= 2,
    }


@v1.get("/metrics")
def v1_metrics():
    """Operational metrics — retry rate, avg latency, P95 latency."""
    try:
        return query_metrics()
    except Exception as exc:
        return {"error": str(exc)}


# ── Root aliases (backward compat — existing Next.js frontend calls these) ───

@app.post("/query", response_model=QueryResponse)
def root_query(req: QueryRequest):
    return _run_query(req)


@app.post("/ingest", response_model=IngestResponse)
async def root_ingest(file: UploadFile = File(...), sector: str = Form(default="cross")):
    return await _run_ingest(file, sector)


@app.get("/sources", response_model=list[SourceItem])
def root_sources():
    return _sources_list()


@app.get("/audit/flagged")
def root_audit_flagged(limit: int = 50):
    return flagged_review_queue(limit=limit)


@app.get("/audit/signals")
def root_audit_signals(days: int = 30):
    return v1_audit_signals(days)


# Mount versioned router
app.include_router(v1)


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
