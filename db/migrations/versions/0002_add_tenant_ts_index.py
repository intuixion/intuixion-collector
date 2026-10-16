"""Add (tenant_id, created_at) compound index for Phase 4 audit export

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-13

Without this index, the Phase 4 audit export query
  SELECT ... FROM query_audit_log WHERE tenant_id = $1 AND created_at BETWEEN $2 AND $3
does a full table scan. At 10k+ rows this becomes noticeably slow.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_tenant_ts",
        "query_audit_log",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_ts", table_name="query_audit_log")
