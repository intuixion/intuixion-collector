"""
intuixion.ai — Retrieval Module

Embeds a query with OpenAI, searches Qdrant with semantic + keyword hybrid,
and returns the top-K most relevant chunks with full metadata.

Usage (CLI):
    python query.py "What are the prescribed minimum benefit conditions?"
    python query.py "POPIA data subject rights" --sector cross --top-k 10
    python query.py "NCA reckless lending" --slug nca_national_credit_act_2005

Usage (library):
    from query import retrieve
    chunks = retrieve("What is the PAYE threshold for 2024?", top_k=5)
"""

import argparse
import json
import os
import threading
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient, models as qmodels
from qdrant_client.models import (
    FieldCondition, Filter, IsEmptyCondition, MatchText, MatchValue, PayloadField,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "intuixion_sa_docs")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

_oai: Optional[OpenAI] = None
_qdrant: Optional[QdrantClient] = None
_clients_lock = threading.Lock()


def _clients() -> tuple[OpenAI, QdrantClient]:
    global _oai, _qdrant
    if _oai is None or _qdrant is None:
        with _clients_lock:
            if _oai is None:
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    raise SystemExit("OPENAI_API_KEY not set. Add it to .env or the shell.")
                _oai = OpenAI(api_key=api_key)
            if _qdrant is None:
                if QDRANT_URL:
                    from urllib.parse import urlparse
                    _p = urlparse(QDRANT_URL)
                    _use_https = _p.scheme == "https"
                    _port = _p.port or (443 if _use_https else 6333)
                    _qdrant = QdrantClient(
                        host=_p.hostname,
                        port=_port,
                        https=_use_https,
                        api_key=QDRANT_API_KEY,
                    )
                else:
                    _qdrant = QdrantClient(":memory:")
    return _oai, _qdrant


def _embed(text: str) -> list[float]:
    oai, _ = _clients()
    return oai.embeddings.create(model=EMBEDDING_MODEL, input=[text]).data[0].embedding


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def retrieve(
    query: str,
    top_k: int = 8,
    sector: Optional[str] = None,
    slug: Optional[str] = None,
    keyword: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> list[dict]:
    """
    Semantic search over the Qdrant collection with optional keyword post-filter.

    Args:
        query:     Natural-language question to search for.
        top_k:     Number of results to return.
        sector:    Filter by sector (cross | healthcare | financial | retail).
        slug:      Filter to a specific source document by slug.
        keyword:   Term that must appear in the chunk text (case-insensitive substring).
        tenant_id: Restrict to chunks belonging to this tenant (multi-tenancy).

    Returns:
        List of chunk dicts ordered by relevance score.
    """
    _, qdrant = _clients()

    conditions = []
    if sector:
        conditions.append(FieldCondition(key="sector", match=MatchValue(value=sector)))
    if slug:
        conditions.append(FieldCondition(key="slug", match=MatchValue(value=slug)))
    # Public-corpus points carry no tenant_id. A tenant sees the public corpus plus its
    # own documents; a caller without a tenant sees the public corpus only.
    public_corpus = IsEmptyCondition(is_empty=PayloadField(key="tenant_id"))
    if tenant_id:
        conditions.append(Filter(should=[
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            public_corpus,
        ]))
    else:
        conditions.append(public_corpus)
    if keyword:  # must stay last — the fallback below drops conditions[-1]
        conditions.append(FieldCondition(key="text", match=MatchText(text=keyword)))

    query_filter = Filter(must=conditions) if conditions else None

    vector = _embed(query)
    fetch_k = max(top_k * 4, 30)

    def _search(filt):
        r = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=fetch_k,
            query_filter=filt,
            with_payload=True,
        )
        return r.points

    try:
        results = _search(query_filter)
    except Exception as exc:
        # MatchText requires a payload text index — retry without the keyword filter
        # and fall back to substring post-filtering below. The tenant condition is
        # always present, so the retry never searches unfiltered.
        if not keyword:
            raise exc
        results = _search(Filter(must=conditions[:-1]))

    chunks = []
    for r in results:
        payload = r.payload or {}
        text = payload.get("text", "")
        if keyword and keyword.lower() not in text.lower():
            continue
        chunks.append({
            "score": round(r.score, 4),
            "text": text,
            "slug": payload.get("slug"),
            "name": payload.get("name"),
            "sector": payload.get("sector"),
            "source_type": payload.get("source_type"),
            "file": payload.get("file"),
            "source_url": payload.get("source_url"),
            "chunk_idx": payload.get("chunk_idx"),
            "chunk_count": payload.get("chunk_count"),
            "ingested_at": payload.get("ingested_at"),
        })
        if len(chunks) >= top_k:
            break

    return chunks


def format_results(chunks: list[dict], verbose: bool = False) -> str:
    if not chunks:
        return "No results found."
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(
            f"[{i}] score={c['score']}  {c['slug']}  "
            f"(chunk {c['chunk_idx']}/{c['chunk_count']})"
        )
        lines.append(f"    {c['name']}")
        if verbose:
            lines.append(f"    {c['source_url']}")
        preview = c["text"][:400].replace("\n", " ")
        lines.append(f"    {preview}{'...' if len(c['text']) > 400 else ''}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="Query the intuixion.ai SA regulatory corpus")
    p.add_argument("query", help="Natural-language question")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--sector", choices=["cross", "healthcare", "financial", "retail"])
    p.add_argument("--slug", help="Restrict to one source slug")
    p.add_argument("--keyword", help="Term that must appear in result text")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    chunks = retrieve(
        query=args.query,
        top_k=args.top_k,
        sector=args.sector,
        slug=args.slug,
        keyword=args.keyword,
    )

    if args.as_json:
        print(json.dumps(chunks, indent=2))
    else:
        print(format_results(chunks, verbose=args.verbose))


if __name__ == "__main__":
    main()
