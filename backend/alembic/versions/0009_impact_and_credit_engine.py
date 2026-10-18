"""Add Impact Ledger, Methodologies, Eligibility Assessments, Credit Batches and Retirements.

Revision ID: 0009_impact_and_credit_engine
Revises: 0008_circular_engine
Create Date: 2026-10-18 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009_impact_and_credit_engine"
down_revision: Union[str, None] = "0008_circular_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create methodologies table
    op.create_table(
        "methodologies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("standard_name", sa.String(length=150), nullable=False),
        sa.Column("is_standard_recognized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("registry_name", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_methodologies_code"),
    )
    op.create_index("ix_methodologies_code", "methodologies", ["code"])

    # 2. Create methodology_versions table
    op.create_table(
        "methodology_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("methodology_id", sa.Uuid(), nullable=False),
        sa.Column("version_tag", sa.String(length=50), nullable=False),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_immutable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("eligible_materials", sa.JSON(), nullable=False),
        sa.Column("credit_conversion_factor", sa.Numeric(12, 6), nullable=False),
        sa.Column("credit_unit_name", sa.String(length=50), nullable=False),
        sa.Column("additionality_discount", sa.Numeric(8, 4), nullable=False, server_default="0.0000"),
        sa.Column("baseline_discount", sa.Numeric(8, 4), nullable=False, server_default="0.0000"),
        sa.Column("leakage_deduction", sa.Numeric(8, 4), nullable=False, server_default="0.0000"),
        sa.Column("required_evidence_types", sa.JSON(), nullable=False),
        sa.Column("requires_independent_verification", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("calculation_formula", sa.String(length=255), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["methodology_id"], ["methodologies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("methodology_id", "version_tag", name="uq_methodology_version_tag"),
    )
    op.create_index("ix_methodology_versions_methodology_id", "methodology_versions", ["methodology_id"])
    op.create_index("ix_methodology_versions_activity_type", "methodology_versions", ["activity_type"])

    # 3. Create impact_records table
    op.create_table(
        "impact_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("impact_id", sa.String(length=50), nullable=False),
        sa.Column("outcome_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="VERIFIED"),
        sa.Column("source_recovery_id", sa.Uuid(), nullable=True),
        sa.Column("source_material_batch_id", sa.Uuid(), nullable=True),
        sa.Column("source_upcycling_batch_id", sa.Uuid(), nullable=True),
        sa.Column("verification_record_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("material_type", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("allocated_quantity", sa.Numeric(18, 4), nullable=False, server_default="0.0000"),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="KG"),
        sa.Column("location_name", sa.String(length=255), nullable=False),
        sa.Column("coordinates", sa.JSON(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_manifest", sa.JSON(), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_recovery_id"], ["recovery_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_material_batch_id"], ["material_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_upcycling_batch_id"], ["upcycling_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verification_record_id"], ["verification_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["impact_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["impact_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("impact_id", name="uq_impact_records_impact_id"),
        sa.CheckConstraint("quantity > 0", name="chk_impact_record_quantity_positive"),
        sa.CheckConstraint("allocated_quantity >= 0", name="chk_impact_record_allocated_non_negative"),
        sa.CheckConstraint("allocated_quantity <= quantity", name="chk_impact_record_allocated_lte_quantity"),
    )
    op.create_index("ix_impact_records_impact_id", "impact_records", ["impact_id"])
    op.create_index("ix_impact_records_outcome_type", "impact_records", ["outcome_type"])
    op.create_index("ix_impact_records_status", "impact_records", ["status"])
    op.create_index("ix_impact_records_organization_id", "impact_records", ["organization_id"])
    op.create_index("ix_impact_records_material_type", "impact_records", ["material_type"])
    op.create_index("ix_impact_records_source_recovery_id", "impact_records", ["source_recovery_id"])
    op.create_index("ix_impact_records_source_material_batch_id", "impact_records", ["source_material_batch_id"])

    # 4. Create credit_batches table
    op.create_table(
        "credit_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_number", sa.String(length=60), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("methodology_version_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("issuer_id", sa.Uuid(), nullable=True),
        sa.Column("total_credits", sa.Numeric(18, 4), nullable=False),
        sa.Column("available_credits", sa.Numeric(18, 4), nullable=False),
        sa.Column("retired_credits", sa.Numeric(18, 4), nullable=False, server_default="0.0000"),
        sa.Column("credit_type", sa.String(length=50), nullable=False),
        sa.Column("vintage_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="DRAFT"),
        sa.Column("registry_name", sa.String(length=100), nullable=False, server_default="PLASTIFY_INTERNAL_REGISTRY"),
        sa.Column("registry_batch_id", sa.String(length=100), nullable=True),
        sa.Column("registry_status", sa.String(length=50), nullable=False, server_default="LOCAL_ONLY"),
        sa.Column("is_mock_issuance", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("issuance_notes", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["methodology_version_id"], ["methodology_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issuer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_number", name="uq_credit_batches_batch_number"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_batches_idempotency_key"),
        sa.CheckConstraint("total_credits > 0", name="chk_credit_batch_total_positive"),
        sa.CheckConstraint("available_credits >= 0", name="chk_credit_batch_avail_non_neg"),
        sa.CheckConstraint("retired_credits >= 0", name="chk_credit_batch_retired_non_neg"),
        sa.CheckConstraint("available_credits + retired_credits <= total_credits", name="chk_credit_batch_sum_lte_total"),
    )
    op.create_index("ix_credit_batches_batch_number", "credit_batches", ["batch_number"])
    op.create_index("ix_credit_batches_organization_id", "credit_batches", ["organization_id"])
    op.create_index("ix_credit_batches_status", "credit_batches", ["status"])

    # 5. Create impact_allocations table
    op.create_table(
        "impact_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("impact_record_id", sa.Uuid(), nullable=False),
        sa.Column("credit_batch_id", sa.Uuid(), nullable=True),
        sa.Column("allocated_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="KG"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["impact_record_id"], ["impact_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credit_batch_id"], ["credit_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("allocated_quantity > 0", name="chk_impact_alloc_quantity_positive"),
    )
    op.create_index("ix_impact_allocations_impact_record_id", "impact_allocations", ["impact_record_id"])
    op.create_index("ix_impact_allocations_credit_batch_id", "impact_allocations", ["credit_batch_id"])

    # 6. Create eligibility_assessments table
    op.create_table(
        "eligibility_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_number", sa.String(length=50), nullable=False),
        sa.Column("impact_record_id", sa.Uuid(), nullable=False),
        sa.Column("methodology_version_id", sa.Uuid(), nullable=False),
        sa.Column("assessor_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("gross_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("eligible_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_credit_units", sa.Numeric(18, 4), nullable=False),
        sa.Column("validation_checklist", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("calculation_snapshot", sa.JSON(), nullable=False),
        sa.Column("is_reproducible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["impact_record_id"], ["impact_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["methodology_version_id"], ["methodology_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_number", name="uq_eligibility_assessments_number"),
        sa.CheckConstraint("gross_quantity >= 0", name="chk_assessment_gross_non_neg"),
        sa.CheckConstraint("eligible_quantity >= 0", name="chk_assessment_eligible_non_neg"),
        sa.CheckConstraint("net_credit_units >= 0", name="chk_assessment_net_credits_non_neg"),
    )
    op.create_index("ix_eligibility_assessments_number", "eligibility_assessments", ["assessment_number"])
    op.create_index("ix_eligibility_assessments_impact_id", "eligibility_assessments", ["impact_record_id"])
    op.create_index("ix_eligibility_assessments_status", "eligibility_assessments", ["status"])

    # 7. Create plastic_credits table
    op.create_table(
        "plastic_credits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("credit_batch_id", sa.Uuid(), nullable=False),
        sa.Column("serial_number", sa.String(length=100), nullable=False),
        sa.Column("serial_start", sa.Integer(), nullable=False),
        sa.Column("serial_end", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("owner_organization_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="ACTIVE"),
        sa.Column("vintage_year", sa.Integer(), nullable=False),
        sa.Column("credit_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["credit_batch_id"], ["credit_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("serial_number", name="uq_plastic_credits_serial_number"),
        sa.CheckConstraint("quantity > 0", name="chk_credit_quantity_positive"),
        sa.CheckConstraint("serial_start <= serial_end", name="chk_credit_serial_range"),
    )
    op.create_index("ix_plastic_credits_serial_number", "plastic_credits", ["serial_number"])
    op.create_index("ix_plastic_credits_credit_batch_id", "plastic_credits", ["credit_batch_id"])
    op.create_index("ix_plastic_credits_owner_organization_id", "plastic_credits", ["owner_organization_id"])
    op.create_index("ix_plastic_credits_status", "plastic_credits", ["status"])

    # 8. Create credit_transactions table
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.String(length=60), nullable=False),
        sa.Column("credit_batch_id", sa.Uuid(), nullable=False),
        sa.Column("credit_id", sa.Uuid(), nullable=True),
        sa.Column("tx_type", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("from_organization_id", sa.Uuid(), nullable=True),
        sa.Column("to_organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("audit_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["credit_batch_id"], ["credit_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credit_id"], ["plastic_credits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["from_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_credit_transactions_tx_id"),
    )
    op.create_index("ix_credit_transactions_tx_id", "credit_transactions", ["transaction_id"])
    op.create_index("ix_credit_transactions_credit_batch_id", "credit_transactions", ["credit_batch_id"])
    op.create_index("ix_credit_transactions_idempotency_key", "credit_transactions", ["idempotency_key"])

    # 9. Create credit_retirements table
    op.create_table(
        "credit_retirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("retirement_id", sa.String(length=60), nullable=False),
        sa.Column("credit_batch_id", sa.Uuid(), nullable=False),
        sa.Column("credit_id", sa.Uuid(), nullable=True),
        sa.Column("retiring_organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("beneficiary_name", sa.String(length=255), nullable=False),
        sa.Column("retirement_reason", sa.Text(), nullable=False),
        sa.Column("certificate_id", sa.String(length=80), nullable=False),
        sa.Column("certificate_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["credit_batch_id"], ["credit_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credit_id"], ["plastic_credits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["retiring_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("retirement_id", name="uq_credit_retirements_id"),
        sa.UniqueConstraint("certificate_id", name="uq_credit_retirements_certificate_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_retirements_idempotency_key"),
        sa.CheckConstraint("quantity > 0", name="chk_retirement_quantity_positive"),
    )
    op.create_index("ix_credit_retirements_retirement_id", "credit_retirements", ["retirement_id"])
    op.create_index("ix_credit_retirements_certificate_id", "credit_retirements", ["certificate_id"])
    op.create_index("ix_credit_retirements_retiring_org_id", "credit_retirements", ["retiring_organization_id"])


def downgrade() -> None:
    op.drop_table("credit_retirements")
    op.drop_table("credit_transactions")
    op.drop_table("plastic_credits")
    op.drop_table("eligibility_assessments")
    op.drop_table("impact_allocations")
    op.drop_table("credit_batches")
    op.drop_table("impact_records")
    op.drop_table("methodology_versions")
    op.drop_table("methodologies")
