"""Add the standalone boost-integrated-unit (升压一体机) tables; cabinet tables are unchanged."""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "boost_projects" not in existing:
        op.create_table(
            "boost_projects",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("template_id", sa.String(36), sa.ForeignKey("templates.id"), nullable=False, index=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("document_number", sa.String(100), nullable=False),
            sa.Column("document_version", sa.String(30), nullable=False),
            sa.Column("fields", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
            *_timestamps(),
        )
    if "boost_source_files" not in existing:
        op.create_table(
            "boost_source_files",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("boost_projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("original_path", sa.Text(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("parser_version", sa.String(30), nullable=False),
            sa.Column("document", sa.JSON(), nullable=True),
            sa.Column("issues", sa.JSON(), nullable=False),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            *_timestamps(),
        )
    if "boost_generation_tasks" not in existing:
        op.create_table(
            "boost_generation_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("boost_projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, index=True),
            sa.Column("phase", sa.String(50), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
            sa.Column("input_snapshot", sa.JSON(), nullable=False),
            sa.Column("lease_owner", sa.String(100), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("progress_percent", sa.Integer(), nullable=False),
            sa.Column("progress_message", sa.String(500), nullable=False),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("diagnostics", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(80), nullable=True),
            sa.Column("error_detail", sa.Text(), nullable=True),
            *_timestamps(),
        )
    if "boost_generated_documents" not in existing:
        op.create_table(
            "boost_generated_documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("boost_projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("task_id", sa.String(36), sa.ForeignKey("boost_generation_tasks.id"), nullable=False, unique=True),
            sa.Column("file_path", sa.Text(), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("template_version", sa.String(30), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("validation_report", sa.JSON(), nullable=False),
            *_timestamps(),
        )


def downgrade():
    for table in ("boost_generated_documents", "boost_generation_tasks", "boost_source_files", "boost_projects"):
        op.drop_table(table)
