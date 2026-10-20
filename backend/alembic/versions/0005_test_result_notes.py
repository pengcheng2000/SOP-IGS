"""Per-test-item result description.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project_test_items") as batch:
        batch.add_column(sa.Column("result_note", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("project_test_items") as batch:
        batch.drop_column("result_note")
