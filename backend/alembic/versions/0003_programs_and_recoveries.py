"""Add corporate programs, recovery events, and audit history schema.

Revision ID: 0003_programs_and_recoveries
Revises: 0002_auth_and_organizations
Create Date: 2026-10-14 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_programs_and_recoveries"
down_revision: Union[str, None] = "0002_auth_and_organizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create programs table
    op.create_table(
        "programs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("region", sa.String(length=50), nullable=False, server_default="GLOBAL"),
        sa.Column("target_kg", sa.Float(), nullable=False),
        sa.Column("collected_kg", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("allowed_material_types", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_programs_id"), "programs", ["id"], unique=False)
    op.create_index(op.f("ix_programs_organization_id"), "programs", ["organization_id"], unique=False)
    op.create_index(op.f("ix_programs_name"), "programs", ["name"], unique=False)
    op.create_index(op.f("ix_programs_region"), "programs", ["region"], unique=False)
    op.create_index(op.f("ix_programs_status"), "programs", ["status"], unique=False)

    # 2. Create program_partners table
    op.create_table(
        "program_partners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_role", sa.String(length=50), nullable=False, server_default="COLLECTOR"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "organization_id", name="uq_program_partner"),
    )
    op.create_index(op.f("ix_program_partners_id"), "program_partners", ["id"], unique=False)
    op.create_index(op.f("ix_program_partners_program_id"), "program_partners", ["program_id"], unique=False)
    op.create_index(op.f("ix_program_partners_organization_id"), "program_partners", ["organization_id"], unique=False)

    # 3. Create recovery_sequences table
    op.create_table(
        "recovery_sequences",
        sa.Column("prefix", sa.String(length=50), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("prefix"),
    )

    # 4. Create recovery_events table
    op.create_table(
        "recovery_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_id", sa.String(length=50), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("collector_id", sa.Uuid(), nullable=False),
        sa.Column("collector_organization_id", sa.Uuid(), nullable=False),
        sa.Column("material_type", sa.String(length=50), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("collection_location", sa.String(length=255), nullable=False),
        sa.Column("collection_coordinates", sa.JSON(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collector_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["collector_organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recovery_events_id"), "recovery_events", ["id"], unique=False)
    op.create_index(op.f("ix_recovery_events_recovery_id"), "recovery_events", ["recovery_id"], unique=True)
    op.create_index(op.f("ix_recovery_events_program_id"), "recovery_events", ["program_id"], unique=False)
    op.create_index(op.f("ix_recovery_events_collector_id"), "recovery_events", ["collector_id"], unique=False)
    op.create_index(op.f("ix_recovery_events_collector_organization_id"), "recovery_events", ["collector_organization_id"], unique=False)
    op.create_index(op.f("ix_recovery_events_material_type"), "recovery_events", ["material_type"], unique=False)
    op.create_index(op.f("ix_recovery_events_status"), "recovery_events", ["status"], unique=False)

    # 5. Create recovery_event_histories table
    op.create_table(
        "recovery_event_histories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_event_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=True),
        sa.Column("to_status", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recovery_event_id"], ["recovery_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recovery_event_histories_id"), "recovery_event_histories", ["id"], unique=False)
    op.create_index(op.f("ix_recovery_event_histories_recovery_event_id"), "recovery_event_histories", ["recovery_event_id"], unique=False)
    op.create_index(op.f("ix_recovery_event_histories_actor_id"), "recovery_event_histories", ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_table("recovery_event_histories")
    op.drop_table("recovery_events")
    op.drop_table("recovery_sequences")
    op.drop_table("program_partners")
    op.drop_table("programs")
