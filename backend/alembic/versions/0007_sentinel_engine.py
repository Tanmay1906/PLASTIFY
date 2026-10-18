"""Add Sentinel risk and anomaly detection engine schema.

Revision ID: 0007_sentinel_engine
Revises: 0006_verification_engine
Create Date: 2026-10-17 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007_sentinel_engine"
down_revision: Union[str, None] = "0006_verification_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create sentinel_results table
    op.create_table(
        "sentinel_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_id", sa.Uuid(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("risk_level", sa.String(length=50), nullable=False, server_default="LOW"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("flags_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("high_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("medium_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="COMPLETED"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recovery_id"], ["recovery_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sentinel_results_recovery_id"), "sentinel_results", ["recovery_id"], unique=True)
    op.create_index(op.f("ix_sentinel_results_risk_level"), "sentinel_results", ["risk_level"], unique=False)
    op.create_index(op.f("ix_sentinel_results_status"), "sentinel_results", ["status"], unique=False)
    op.create_index(op.f("ix_sentinel_results_created_at"), "sentinel_results", ["created_at"], unique=False)

    # 2. Create sentinel_flags table
    op.create_table(
        "sentinel_flags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("detector", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence_reference", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["sentinel_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sentinel_flags_result_id"), "sentinel_flags", ["result_id"], unique=False)
    op.create_index(op.f("ix_sentinel_flags_detector"), "sentinel_flags", ["detector"], unique=False)
    op.create_index(op.f("ix_sentinel_flags_severity"), "sentinel_flags", ["severity"], unique=False)
    op.create_index(op.f("ix_sentinel_flags_created_at"), "sentinel_flags", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("sentinel_flags")
    op.drop_table("sentinel_results")
