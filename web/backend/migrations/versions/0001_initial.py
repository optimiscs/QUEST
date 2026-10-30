"""Initial viewer schema. Keep this migration independent of application models."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runs",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("metadata_json", JSONB, nullable=False),
        sa.Column("run_json", JSONB, nullable=False),
        sa.Column("envelope_json", JSONB, nullable=False),
        sa.Column("counts", JSONB, nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_table(
        "traces",
        sa.Column("run_id", sa.String(255), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.UniqueConstraint("run_id", "position"),
    )
    op.create_table(
        "trace_payloads",
        sa.Column("run_id", sa.String(255), primary_key=True),
        sa.Column("trace_id", sa.String(255), primary_key=True),
        sa.Column("body", JSONB, nullable=False),
        sa.ForeignKeyConstraint(["run_id", "trace_id"], ["traces.run_id", "traces.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "ingestion_sources",
        sa.Column("run_id", sa.String(255), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("path", sa.String, nullable=False),
        sa.Column("mtime_ns", sa.BigInteger, nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reports",
        sa.Column("name", sa.String(255), primary_key=True),
        sa.Column("body", JSONB, nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
    )


def downgrade():
    for name in ["reports", "ingestion_sources", "trace_payloads", "traces", "runs"]:
        op.drop_table(name)
