"""
intuixion.ai — DocuRAG FastAPI Backend

Exposes the RAG pipeline as an HTTP API consumed by the Next.js frontend.

Install:
    pip install fastapi uvicorn[standard] python-multipart

Run:
    uvicorn api:app --reload --port 8000

Endpoints:
    POST /query          — semantic search + Claude answer
    POST /ingest         — upload and ingest a PDF
    GET  /sources        — list ingested sources
    GET  /health         — health check
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

app = FastAPI(
    title="intuixion.ai DocuRAG API",
    description="SA Regulatory Document Intelligence",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://intuixion.ai",
        "https://demo.intuixion.ai",
        "https://app.intuixion.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str
    sector: Optional[str] = None
    slug: Optional[str] = None
    top_k: int = 8


class CitationItem(BaseModel):
    slug: str
    name: str
    sector: str
    chunk_idx: int
    chunk_count: int
    score: float
    text: str
    source_url: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationItem]
    retrieval_ms: int
    answer_ms: int


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
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "intuixion-docurag"}


@app.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    retrieve = _get_retriever()
    run_agent = _get_agent()

    # Retrieve relevant chunks
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

    # Generate answer via Claude agent
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
        )
        for c in chunks
    ]

    return QueryResponse(
        answer=answer,
        citations=citations,
        retrieval_ms=retrieval_ms,
        answer_ms=answer_ms,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(
    file: UploadFile = File(...),
    sector: str = Form(default="cross"),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save to a temp directory, ingest, clean up
    with tempfile.TemporaryDirectory() as tmp_dir:
        dest = Path(tmp_dir) / file.filename
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            from ingest import (
                IngestState,
                extract_pages,
                pages_to_text,
                chunk_text,
                is_quality_chunk,
                embed_batch,
                upsert_chunks,
                file_sha256,
                get_qdrant,
                ensure_collection,
                COLLECTION_NAME,
                EMBEDDING_MODEL,
                EMBEDDING_DIMS,
                QDRANT_URL,
                QDRANT_API_KEY,
                STATE_PATH,
                DEFAULT_CHUNK_SIZE,
                DEFAULT_CHUNK_OVERLAP,
            )
            from openai import OpenAI

            sha256 = file_sha256(dest)
            pages, _ = extract_pages(dest)
            full_text = pages_to_text(pages, "by_title")
            if not full_text.strip():
                return IngestResponse(
                    status="skip",
                    filename=file.filename,
                    chunks=0,
                    message="No extractable text found in this PDF.",
                )

            raw_chunks = chunk_text(full_text, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP, "by_title")
            chunks_filtered = [c for c in raw_chunks if is_quality_chunk(c)]
            if not chunks_filtered:
                return IngestResponse(
                    status="skip",
                    filename=file.filename,
                    chunks=0,
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
                status="ok",
                filename=file.filename,
                chunks=n,
                message=f"Successfully ingested {n} chunks.",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sources", response_model=list[SourceItem])
def sources_endpoint():
    import json
    from collections import defaultdict

    manifest_path = Path("data/manifest.json")
    if not manifest_path.exists():
        return []

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Also load state to get chunk counts
    state_path = Path("data/ingest_state.json")
    state_chunks: dict[str, int] = {}
    if state_path.exists():
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
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


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
