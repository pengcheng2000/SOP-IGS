"""Separate project sample photos from selectable test items."""
from alembic import op
from app.sample_migration import upgrade_sample_scope

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_sample_scope(op.get_bind())


def downgrade():
    raise RuntimeError("Sample photo data must be exported before an explicitly planned downgrade.")
