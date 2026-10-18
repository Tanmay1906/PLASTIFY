"""Add verification engine schema.

Revision ID: 0006_verification_engine
Revises: 0005_logistics_and_delivery
Create Date: 2026-10-17 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_verification_engine"
down_revision: Union[str, None] = "0005_logistics_and_delivery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create verification_records table
    op.create_table(
        "verification_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_code", sa.String(length=50), nullable=False),
        sa.Column("recovery_id", sa.Uuid(), nullable=False),
        sa.Column("verifier_id", sa.Uuid(), nullable=False),
        sa.Column("verifier_organization_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("verified_weight_kg", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("checklist", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recovery_id"], ["recovery_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verifier_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verifier_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verification_records_verification_code"), "verification_records", ["verification_code"], unique=True)
    op.create_index(op.f("ix_verification_records_recovery_id"), "verification_records", ["recovery_id"], unique=False)
    op.create_index(op.f("ix_verification_records_verifier_id"), "verification_records", ["verifier_id"], unique=False)
    op.create_index(op.f("ix_verification_records_verifier_organization_id"), "verification_records", ["verifier_organization_id"], unique=False)
    op.create_index(op.f("ix_verification_records_decision"), "verification_records", ["decision"], unique=False)
    op.create_index(op.f("ix_verification_records_created_at"), "verification_records", ["created_at"], unique=False)

    # 2. Create verification_findings table
    op.create_table(
        "verification_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_id", sa.Uuid(), nullable=False),
        sa.Column("verification_record_id", sa.Uuid(), nullable=True),
        sa.Column("finder_id", sa.Uuid(), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finder_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recovery_id"], ["recovery_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["verification_record_id"], ["verification_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verification_findings_recovery_id"), "verification_findings", ["recovery_id"], unique=False)
    op.create_index(op.f("ix_verification_findings_verification_record_id"), "verification_findings", ["verification_record_id"], unique=False)
    op.create_index(op.f("ix_verification_findings_finder_id"), "verification_findings", ["finder_id"], unique=False)
    op.create_index(op.f("ix_verification_findings_severity"), "verification_findings", ["severity"], unique=False)
    op.create_index(op.f("ix_verification_findings_category"), "verification_findings", ["category"], unique=False)
    op.create_index(op.f("ix_verification_findings_is_resolved"), "verification_findings", ["is_resolved"], unique=False)
    op.create_index(op.f("ix_verification_findings_created_at"), "verification_findings", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("verification_findings")
    op.drop_table("verification_records")
