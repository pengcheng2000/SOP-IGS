"""Idempotent upgrade for existing bootstrap-managed databases."""
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def upgrade_sample_scope(connection):
    if "scope" in {c["name"] for c in sa.inspect(connection).get_columns("photo_groups")}:
        return
    operations = Operations(MigrationContext.configure(connection))
    with operations.batch_alter_table("photo_groups") as batch:
        batch.add_column(sa.Column("scope", sa.String(20), nullable=False, server_default="test_item"))
        batch.alter_column("test_item_id", existing_type=sa.String(80), nullable=True)
        batch.create_check_constraint("ck_photo_group_scope", "(scope = 'sample' AND test_item_id IS NULL) OR (scope = 'test_item' AND test_item_id IS NOT NULL)")
    operations.create_index("uq_sample_group_key", "photo_groups", ["project_id", "key"], unique=True,
                            sqlite_where=sa.text("scope = 'sample'"), postgresql_where=sa.text("scope = 'sample'"))
