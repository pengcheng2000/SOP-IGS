"""Photo group definitions and document task progress.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_photo_group_definitions",
        sa.Column("id", sa.String(length=160), primary_key=True),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("test_item_id", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("requiredness", sa.String(length=20), nullable=False, server_default="recommended"),
        sa.Column("min_photos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("layout_profile", sa.String(length=40), nullable=False, server_default="adaptive_grid"),
        sa.Column("preferred_columns", sa.Integer(), nullable=True),
        sa.Column("hint", sa.String(length=500), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_item_id"], ["test_items.id"]),
        sa.UniqueConstraint("template_id", "test_item_id", "key"),
    )
    op.create_index(
        "ix_template_photo_group_definitions_template_id",
        "template_photo_group_definitions",
        ["template_id"],
    )
    op.create_index(
        "ix_template_photo_group_definitions_test_item_id",
        "template_photo_group_definitions",
        ["test_item_id"],
    )
    with op.batch_alter_table("photo_groups") as batch:
        batch.add_column(sa.Column("template_group_id", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("source", sa.String(length=20), nullable=False, server_default="custom"))
        batch.add_column(sa.Column("requiredness", sa.String(length=20), nullable=False, server_default="recommended"))
        batch.add_column(sa.Column("min_photos", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("layout_profile", sa.String(length=40), nullable=False, server_default="adaptive_grid"))
        batch.add_column(sa.Column("preferred_columns", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("hint", sa.String(length=500), nullable=False, server_default=""))
        batch.create_index("ix_photo_groups_template_group_id", ["template_group_id"])
        batch.create_foreign_key(
            "fk_photo_groups_template_group_id",
            "template_photo_group_definitions",
            ["template_group_id"],
            ["id"],
        )

    with op.batch_alter_table("document_generation_tasks") as batch:
        batch.add_column(sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("progress_message", sa.String(length=500), nullable=False, server_default="等待 Word Worker"))
        batch.add_column(sa.Column("phase_started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("diagnostics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    op.create_table(
        "document_task_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("phase", sa.String(length=50), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["document_generation_tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_task_events_task_id", "document_task_events", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_document_task_events_task_id", table_name="document_task_events")
    op.drop_table("document_task_events")
    with op.batch_alter_table("document_generation_tasks") as batch:
        for column in (
            "diagnostics",
            "completed_at",
            "started_at",
            "phase_started_at",
            "progress_message",
            "progress_percent",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("photo_groups") as batch:
        batch.drop_constraint("fk_photo_groups_template_group_id", type_="foreignkey")
        batch.drop_index("ix_photo_groups_template_group_id")
        for column in (
            "hint",
            "preferred_columns",
            "layout_profile",
            "min_photos",
            "requiredness",
            "source",
            "template_group_id",
        ):
            batch.drop_column(column)
    op.drop_index(
        "ix_template_photo_group_definitions_test_item_id",
        table_name="template_photo_group_definitions",
    )
    op.drop_index(
        "ix_template_photo_group_definitions_template_id",
        table_name="template_photo_group_definitions",
    )
    op.drop_table("template_photo_group_definitions")

