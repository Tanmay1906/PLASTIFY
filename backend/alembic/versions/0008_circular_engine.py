"""Add Circular Economy: Recycling, Upcycling, Material and Product Passports.

Revision ID: 0008_circular_engine
Revises: 0007_sentinel_engine
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008_circular_engine"
down_revision: Union[str, None] = "0007_sentinel_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create material_batches table
    op.create_table(
        "material_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.String(length=50), nullable=False),
        sa.Column("recycler_organization_id", sa.Uuid(), nullable=False),
        sa.Column("processor_id", sa.Uuid(), nullable=False),
        sa.Column("material_type", sa.String(length=50), nullable=False),
        sa.Column("input_weight_kg", sa.Float(), nullable=False),
        sa.Column("recycled_output_kg", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("residual_kg", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("processing_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="CREATED"),
        sa.Column("verification_reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recycler_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_material_batches_batch_id"), "material_batches", ["batch_id"], unique=True)
    op.create_index(op.f("ix_material_batches_recycler_organization_id"), "material_batches", ["recycler_organization_id"], unique=False)
    op.create_index(op.f("ix_material_batches_processor_id"), "material_batches", ["processor_id"], unique=False)
    op.create_index(op.f("ix_material_batches_material_type"), "material_batches", ["material_type"], unique=False)
    op.create_index(op.f("ix_material_batches_status"), "material_batches", ["status"], unique=False)

    # 2. Create material_batch_items table
    op.create_table(
        "material_batch_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_batch_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_event_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_weight_kg", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["material_batch_id"], ["material_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recovery_event_id"], ["recovery_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_batch_id", "recovery_event_id", name="uq_batch_recovery"),
    )
    op.create_index(op.f("ix_material_batch_items_material_batch_id"), "material_batch_items", ["material_batch_id"], unique=False)
    op.create_index(op.f("ix_material_batch_items_recovery_event_id"), "material_batch_items", ["recovery_event_id"], unique=False)

    # 3. Create material_batch_evidences table
    op.create_table(
        "material_batch_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_batch_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False, server_default="PROCESSING_PROOF"),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256_hash", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["material_batch_id"], ["material_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_material_batch_evidences_material_batch_id"), "material_batch_evidences", ["material_batch_id"], unique=False)
    op.create_index(op.f("ix_material_batch_evidences_evidence_type"), "material_batch_evidences", ["evidence_type"], unique=False)

    # 4. Create material_passports table
    op.create_table(
        "material_passports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("passport_code", sa.String(length=100), nullable=False),
        sa.Column("material_batch_id", sa.Uuid(), nullable=False),
        sa.Column("qr_code_identifier", sa.String(length=100), nullable=False),
        sa.Column("issuer_organization_id", sa.Uuid(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["material_batch_id"], ["material_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issuer_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_material_passports_passport_code"), "material_passports", ["passport_code"], unique=True)
    op.create_index(op.f("ix_material_passports_material_batch_id"), "material_passports", ["material_batch_id"], unique=True)
    op.create_index(op.f("ix_material_passports_qr_code_identifier"), "material_passports", ["qr_code_identifier"], unique=True)

    # 5. Create upcycling_batches table
    op.create_table(
        "upcycling_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.String(length=50), nullable=False),
        sa.Column("upcycler_organization_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("product_type", sa.String(length=100), nullable=False),
        sa.Column("total_input_material_kg", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("quantity_produced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_of_measure", sa.String(length=20), nullable=False, server_default="UNITS"),
        sa.Column("quality_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quality_rating", sa.String(length=50), nullable=True),
        sa.Column("quality_notes", sa.Text(), nullable=True),
        sa.Column("quality_verified_by_id", sa.Uuid(), nullable=True),
        sa.Column("quality_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="CREATED"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["upcycler_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quality_verified_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_upcycling_batches_batch_id"), "upcycling_batches", ["batch_id"], unique=True)
    op.create_index(op.f("ix_upcycling_batches_upcycler_organization_id"), "upcycling_batches", ["upcycler_organization_id"], unique=False)
    op.create_index(op.f("ix_upcycling_batches_creator_id"), "upcycling_batches", ["creator_id"], unique=False)
    op.create_index(op.f("ix_upcycling_batches_product_type"), "upcycling_batches", ["product_type"], unique=False)
    op.create_index(op.f("ix_upcycling_batches_quality_verified"), "upcycling_batches", ["quality_verified"], unique=False)
    op.create_index(op.f("ix_upcycling_batches_status"), "upcycling_batches", ["status"], unique=False)

    # 6. Create upcycling_allocations table
    op.create_table(
        "upcycling_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upcycling_batch_id", sa.Uuid(), nullable=False),
        sa.Column("material_batch_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_weight_kg", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["upcycling_batch_id"], ["upcycling_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_batch_id"], ["material_batches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upcycling_batch_id", "material_batch_id", name="uq_upcycling_allocation"),
    )
    op.create_index(op.f("ix_upcycling_allocations_upcycling_batch_id"), "upcycling_allocations", ["upcycling_batch_id"], unique=False)
    op.create_index(op.f("ix_upcycling_allocations_material_batch_id"), "upcycling_allocations", ["material_batch_id"], unique=False)

    # 7. Create upcycling_batch_evidences table
    op.create_table(
        "upcycling_batch_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upcycling_batch_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False, server_default="PRODUCTION_PROOF"),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256_hash", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["upcycling_batch_id"], ["upcycling_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_upcycling_batch_evidences_upcycling_batch_id"), "upcycling_batch_evidences", ["upcycling_batch_id"], unique=False)

    # 8. Create products table
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_code", sa.String(length=100), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_type", sa.String(length=100), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("upcycling_batch_id", sa.Uuid(), nullable=False),
        sa.Column("weight_per_unit_kg", sa.Float(), nullable=True),
        sa.Column("recycled_content_percentage", sa.Float(), nullable=False, server_default="100.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["upcycling_batch_id"], ["upcycling_batches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_products_product_code"), "products", ["product_code"], unique=True)
    op.create_index(op.f("ix_products_sku"), "products", ["sku"], unique=False)
    op.create_index(op.f("ix_products_name"), "products", ["name"], unique=False)
    op.create_index(op.f("ix_products_product_type"), "products", ["product_type"], unique=False)
    op.create_index(op.f("ix_products_organization_id"), "products", ["organization_id"], unique=False)
    op.create_index(op.f("ix_products_upcycling_batch_id"), "products", ["upcycling_batch_id"], unique=False)

    # 9. Create product_passports table
    op.create_table(
        "product_passports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("passport_id", sa.String(length=100), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("upcycling_batch_id", sa.Uuid(), nullable=False),
        sa.Column("qr_code_url", sa.String(length=500), nullable=True),
        sa.Column("public_url", sa.String(length=500), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upcycling_batch_id"], ["upcycling_batches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_product_passports_passport_id"), "product_passports", ["passport_id"], unique=True)
    op.create_index(op.f("ix_product_passports_product_id"), "product_passports", ["product_id"], unique=False)
    op.create_index(op.f("ix_product_passports_upcycling_batch_id"), "product_passports", ["upcycling_batch_id"], unique=False)


def downgrade() -> None:
    op.drop_table("product_passports")
    op.drop_table("products")
    op.drop_table("upcycling_batch_evidences")
    op.drop_table("upcycling_allocations")
    op.drop_table("upcycling_batches")
    op.drop_table("material_passports")
    op.drop_table("material_batch_evidences")
    op.drop_table("material_batch_items")
    op.drop_table("material_batches")
