"""Keep archived runs readable while reconciling the current workspace manifest."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("runs", "listed")
