"""Use JSON for opaque bodies: JSONB cannot preserve escaped U+0000 in tool output."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("trace_payloads", "body", type_=sa.JSON(), postgresql_using="body::json")


def downgrade():
    # Will fail rather than silently discard any U+0000-containing historical output.
    op.alter_column("trace_payloads", "body", type_=JSONB(), postgresql_using="body::jsonb")
