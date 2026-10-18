"""Add logistics and delivery engine schema.

Revision ID: 0005_logistics_and_delivery
Revises: 0004_evidence_and_chain_of_custody
Create Date: 2026-10-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005_logistics_and_delivery"
down_revision: Union[str, None] = "0004_evidence_and_chain_of_custody"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create logistics_assignments table
    op.create_table(
        "logistics_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_code", sa.String(length=100), nullable=False),
        sa.Column("recovery_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("logistics_organization_id", sa.Uuid(), nullable=False),
        sa.Column("destination_organization_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_to_driver_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="ASSIGNED"),
        sa.Column("pickup_location", sa.String(length=255), nullable=False),
        sa.Column("destination_location", sa.String(length=255), nullable=True),
        sa.Column("scheduled_pickup_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_to_driver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["destination_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["logistics_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recovery_id"], ["recovery_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_logistics_assignments_assignment_code"), "logistics_assignments", ["assignment_code"], unique=True)
    op.create_index(op.f("ix_logistics_assignments_recovery_id"), "logistics_assignments", ["recovery_id"], unique=False)
    op.create_index(op.f("ix_logistics_assignments_program_id"), "logistics_assignments", ["program_id"], unique=False)
    op.create_index(op.f("ix_logistics_assignments_logistics_organization_id"), "logistics_assignments", ["logistics_organization_id"], unique=False)
    op.create_index(op.f("ix_logistics_assignments_status"), "logistics_assignments", ["status"], unique=False)

    # 2. Create deliveries table
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_code", sa.String(length=100), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_id", sa.Uuid(), nullable=False),
        sa.Column("logistics_organization_id", sa.Uuid(), nullable=False),
        sa.Column("recycler_organization_id", sa.Uuid(), nullable=True),
        sa.Column("driver_id", sa.Uuid(), nullable=True),
        sa.Column("receiver_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="PENDING"),
        sa.Column("expected_weight_kg", sa.Float(), nullable=False),
        sa.Column("delivered_weight_kg", sa.Float(), nullable=True),
        sa.Column("received_weight_kg", sa.Float(), nullable=True),
        sa.Column("weight_discrepancy_kg", sa.Float(), nullable=True),
        sa.Column("weight_tolerance_pct", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("weight_tolerance_status", sa.String(length=50), nullable=False, server_default="PENDING"),
        sa.Column("pickup_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_transit_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vehicle_number", sa.String(length=100), nullable=True),
        sa.Column("tracking_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("receipt_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["logistics_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["logistics_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["receiver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recovery_id"], ["recovery_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recycler_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_deliveries_delivery_code"), "deliveries", ["delivery_code"], unique=True)
    op.create_index(op.f("ix_deliveries_assignment_id"), "deliveries", ["assignment_id"], unique=True)
    op.create_index(op.f("ix_deliveries_recovery_id"), "deliveries", ["recovery_id"], unique=False)
    op.create_index(op.f("ix_deliveries_status"), "deliveries", ["status"], unique=False)

    # 3. Create delivery_evidences table
    op.create_table(
        "delivery_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False, server_default="DELIVERY_PROOF"),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256_hash", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delivery_evidences_delivery_id"), "delivery_evidences", ["delivery_id"], unique=False)


def downgrade() -> None:
    op.drop_table("delivery_evidences")
    op.drop_table("deliveries")
    op.drop_table("logistics_assignments")
