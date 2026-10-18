"""Add evidence management and chain-of-custody schema.

Revision ID: 0004_evidence_and_chain_of_custody
Revises: 0003_programs_and_recoveries
Create Date: 2026-10-15 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_evidence_and_chain_of_custody"
down_revision: Union[str, None] = "0003_programs_and_recoveries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add custody_status to recovery_events table
    op.add_column(
        "recovery_events",
        sa.Column(
            "custody_status",
            sa.String(length=50),
            nullable=False,
            server_default="CREATED",
        ),
    )
    op.create_index(
        op.f("ix_recovery_events_custody_status"),
        "recovery_events",
        ["custody_status"],
        unique=False,
    )

    # 2. Create evidence metadata table
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("scan_status", sa.String(length=50), nullable=False, server_default="CLEAN"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recovery_id"], ["recovery_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_id"), "evidence", ["id"], unique=False)
    op.create_index(op.f("ix_evidence_recovery_id"), "evidence", ["recovery_id"], unique=False)
    op.create_index(op.f("ix_evidence_uploader_id"), "evidence", ["uploader_id"], unique=False)
    op.create_index(op.f("ix_evidence_storage_key"), "evidence", ["storage_key"], unique=True)
    op.create_index(op.f("ix_evidence_sha256_hash"), "evidence", ["sha256_hash"], unique=False)
    op.create_index(op.f("ix_evidence_type"), "evidence", ["type"], unique=False)
    op.create_index(op.f("ix_evidence_created_at"), "evidence", ["created_at"], unique=False)

    # 3. Create chain_of_custody_events table
    op.create_table(
        "chain_of_custody_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False, server_default="RECOVERY_EVENT"),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("previous_state", sa.String(length=50), nullable=True),
        sa.Column("new_state", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(length=50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chain_of_custody_events_id"), "chain_of_custody_events", ["id"], unique=False)
    op.create_index(op.f("ix_chain_of_custody_events_resource"), "chain_of_custody_events", ["resource"], unique=False)
    op.create_index(op.f("ix_chain_of_custody_events_resource_type"), "chain_of_custody_events", ["resource_type"], unique=False)
    op.create_index(op.f("ix_chain_of_custody_events_resource_id"), "chain_of_custody_events", ["resource_id"], unique=False)
    op.create_index(op.f("ix_chain_of_custody_events_new_state"), "chain_of_custody_events", ["new_state"], unique=False)
    op.create_index(op.f("ix_chain_of_custody_events_actor_id"), "chain_of_custody_events", ["actor_id"], unique=False)
    op.create_index(op.f("ix_chain_of_custody_events_timestamp"), "chain_of_custody_events", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_table("chain_of_custody_events")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_recovery_events_custody_status"), table_name="recovery_events")
    op.drop_column("recovery_events", "custody_status")
