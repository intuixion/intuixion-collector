"""Create query_audit_log table

Revision ID: 0001
Revises:
Create Date: 2026-09-13

This is the authoritative schema for query_audit_log.
The table is also created by audit/logger.py:init_db() for zero-ops startup,
but Alembic is the migration record for schema evolution.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "query_audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("retrieved_chunk_ids", sa.Text),          # JSON array
        sa.Column("source_type_breakdown", sa.Text),        # JSON object
        sa.Column("generated_answer", sa.Text),
        sa.Column("confidence_tier", sa.Text),              # high | medium | low
        sa.Column("validation_status", sa.Text),            # grounded | flagged | not_validated
        sa.Column("flagged_clauses", sa.Text),              # JSON array | NULL
        sa.Column("latency_ms", sa.Integer),
        sa.Column("stage_latency_ms", sa.Text),             # JSON {retrieval, generation, validation}
        sa.Column("user_id", sa.Text),                      # NULL until multi-tenant auth
        sa.Column("session_id", sa.Text),
        sa.Column("case_law_signal", sa.Integer, server_default="0"),
        sa.Column("human_review_requested", sa.Integer, server_default="0"),
    )
    op.create_index("ix_audit_ts", "query_audit_log", ["ts"])
    op.create_index("ix_audit_validation", "query_audit_log", ["validation_status"])
    op.create_index("ix_audit_user", "query_audit_log", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_user", table_name="query_audit_log")
    op.drop_index("ix_audit_validation", table_name="query_audit_log")
    op.drop_index("ix_audit_ts", table_name="query_audit_log")
    op.drop_table("query_audit_log")
