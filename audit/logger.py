"""
Unified query audit log — SQLite-backed (tech direction Section 2).

Every /query call writes a row here. This is the source for:
  - Phase 1 flagged-answer review queue
  - Phase 4 enterprise audit export
  - Phase 5 ISO evidence
  - Demand-signal tracking (case_law_signal, human_review_requested)

SQLite is the right call at solo-founder scale — zero infra overhead,
single file, trivially backed up. Migrate to hosted Postgres when
Phase 4 multi-tenant audit export needs it.
"""

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from audit.encryption import encrypt, decrypt

DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS query_audit_log (
                id                      TEXT PRIMARY KEY,
                tenant_id               TEXT,
                user_id                 TEXT NOT NULL DEFAULT 'anonymous',
                query_text              TEXT NOT NULL,
                retrieved_chunk_ids     TEXT NOT NULL,
                source_type_breakdown   TEXT,
                generated_answer        TEXT NOT NULL,
                confidence_tier         TEXT NOT NULL,
                validation_status       TEXT NOT NULL,
                flagged_clauses         TEXT,
                latency_ms              INTEGER NOT NULL,
                stage_latency_ms        TEXT NOT NULL,
                case_law_signal         INTEGER NOT NULL DEFAULT 0,
                human_review_requested  INTEGER NOT NULL DEFAULT 0,
                created_at              TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_audit_flagged
                ON query_audit_log (validation_status)
                WHERE validation_status = 'flagged';

            CREATE INDEX IF NOT EXISTS idx_audit_case_law
                ON query_audit_log (case_law_signal)
                WHERE case_law_signal = 1;

            CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts
                ON query_audit_log (tenant_id, created_at);
        """)


def log_query(
    *,
    query_text: str,
    retrieved_chunk_ids: list[str],
    source_type_breakdown: dict,
    generated_answer: str,
    confidence_tier: str,
    validation_status: str,
    flagged_clauses: Optional[list] = None,
    latency_ms: int,
    stage_latency_ms: dict,
    tenant_id: Optional[str] = None,
    user_id: str = "anonymous",
) -> str:
    """Persist one query; returns the new row id."""
    row_id = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT INTO query_audit_log (
                   id, tenant_id, user_id, query_text, retrieved_chunk_ids,
                   source_type_breakdown, generated_answer, confidence_tier,
                   validation_status, flagged_clauses, latency_ms, stage_latency_ms,
                   case_law_signal, human_review_requested
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id,
                tenant_id,
                user_id,
                encrypt(query_text),
                json.dumps(retrieved_chunk_ids),
                json.dumps(source_type_breakdown),
                encrypt(generated_answer),
                confidence_tier,
                validation_status,
                json.dumps(flagged_clauses) if flagged_clauses else None,
                latency_ms,
                json.dumps(stage_latency_ms),
                1 if _case_law_signal(query_text, generated_answer) else 0,
                1 if _human_review_signal(query_text) else 0,
            ),
        )
    return row_id


def flagged_review_queue(limit: int = 50) -> list[dict]:
    """Return recent flagged answers for internal review."""
    with _conn() as con:
        rows = con.execute(
            """SELECT id, query_text, generated_answer, flagged_clauses, created_at
               FROM query_audit_log
               WHERE validation_status = 'flagged'
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["query_text"] = decrypt(d.get("query_text"))
        d["generated_answer"] = decrypt(d.get("generated_answer"))
        result.append(d)
    return result


def query_metrics() -> dict:
    """Operational metrics for /v1/metrics endpoint."""
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM query_audit_log").fetchone()[0]
        flagged = con.execute(
            "SELECT COUNT(*) FROM query_audit_log WHERE validation_status='flagged'"
        ).fetchone()[0]
        rows = con.execute(
            "SELECT latency_ms FROM query_audit_log ORDER BY latency_ms"
        ).fetchall()

    avg_ms = round(sum(r[0] for r in rows) / len(rows)) if rows else 0
    p95_ms = rows[max(0, int(len(rows) * 0.95) - 1)][0] if rows else 0
    retry_rate = round(flagged / total, 4) if total else 0.0
    return {
        "total_queries": total,
        "flagged_count": flagged,
        "retry_rate": retry_rate,
        "retry_rate_alert": retry_rate > 0.05,
        "avg_latency_ms": avg_ms,
        "p95_latency_ms": p95_ms,
        "p95_latency_alert": p95_ms > 4000,  # tech direction: P95 < 4s
    }


def demand_signals(days: int = 30) -> dict:
    """
    Count demand signals over the last N days, across distinct users.
    Revisit case law / human-expert review when either hits 2+ distinct users.
    """
    with _conn() as con:
        case_law = con.execute(
            """SELECT COUNT(DISTINCT user_id) FROM query_audit_log
               WHERE case_law_signal = 1
               AND created_at >= datetime('now', ? || ' days')""",
            (f"-{days}",),
        ).fetchone()[0]
        human_review = con.execute(
            """SELECT COUNT(DISTINCT user_id) FROM query_audit_log
               WHERE human_review_requested = 1
               AND created_at >= datetime('now', ? || ' days')""",
            (f"-{days}",),
        ).fetchone()[0]
    return {"case_law_distinct_users": case_law, "human_review_distinct_users": human_review}


# ── Signal detectors ──────────────────────────────────────────────────────────

_CASE_LAW_RE = re.compile(
    r"\b(case law|how have courts|precedent|interpreted by court|"
    r"judicial interpretation|court held|how courts|case of|landmark case|"
    r"constitutional court|supreme court of appeal)\b",
    re.IGNORECASE,
)

# Narrowed per tech direction: only stakes-naming requests count, not casual reassurance
_HUMAN_REVIEW_RE = re.compile(
    r"\b(before we submit|before we file|for sign-off|sign off|"
    r"for the regulator|for the board|for a lawyer|for an attorney|"
    r"qualified professional|legal opinion|get legal advice|"
    r"for compliance sign|for audit purposes)\b",
    re.IGNORECASE,
)


def _case_law_signal(query: str, answer: str) -> bool:
    return bool(_CASE_LAW_RE.search(query) or _CASE_LAW_RE.search(answer))


def _human_review_signal(query: str) -> bool:
    return bool(_HUMAN_REVIEW_RE.search(query))


def update_judge_result(row_id: str, verdicts: list[dict]) -> None:
    """Write Option B grounding-judge verdicts back to the audit row."""
    with _conn() as con:
        con.execute(
            "UPDATE query_audit_log SET flagged_clauses = ? WHERE id = ?",
            (json.dumps(verdicts), row_id),
        )
