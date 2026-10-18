"""Initial backend foundation schema.

Revision ID: 0001_initial_foundation
Revises: 
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create system_audit_logs table
    op.create_table(
        "system_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("component", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_audit_logs_id"), "system_audit_logs", ["id"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_event_type"), "system_audit_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_component"), "system_audit_logs", ["component"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_request_id"), "system_audit_logs", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_audit_logs_request_id"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_component"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_event_type"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_id"), table_name="system_audit_logs")
    op.drop_table("system_audit_logs")
