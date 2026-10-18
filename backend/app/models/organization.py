"""PLASTIFY Organization, Membership, and Partnership Models."""

from enum import Enum
from typing import TYPE_CHECKING, List, Optional
import uuid
from sqlalchemy import (
    Boolean,
    Enum as SQLEnum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class OrganizationType(str, Enum):
    """Business entity classifications within the circular plastic economy."""

    CORPORATE = "CORPORATE"
    COLLECTOR = "COLLECTOR"
    LOGISTICS = "LOGISTICS"
    VERIFIER = "VERIFIER"
    RECYCLER = "RECYCLER"
    UPCYCLER = "UPCYCLER"
    AUDITOR = "AUDITOR"
    REGULATOR = "REGULATOR"


class OrgMemberRole(str, Enum):
    """Internal organization membership permission levels."""

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class PartnerStatus(str, Enum):
    """Lifecycle state of an inter-organization partnership agreement."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Organization entity participating in plastic circularity tracking."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(
        String(220), unique=True, nullable=False, index=True
    )
    org_type: Mapped[OrganizationType] = mapped_column(
        SQLEnum(OrganizationType, name="org_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    registration_number: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, unique=True
    )
    tax_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="Global")
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User",
        foreign_keys="User.organization_id",
        back_populates="organization",
    )
    members: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    outgoing_partnerships: Mapped[List["PartnerRelationship"]] = relationship(
        "PartnerRelationship",
        foreign_keys="PartnerRelationship.initiator_org_id",
        back_populates="initiator_org",
        cascade="all, delete-orphan",
    )
    incoming_partnerships: Mapped[List["PartnerRelationship"]] = relationship(
        "PartnerRelationship",
        foreign_keys="PartnerRelationship.partner_org_id",
        back_populates="partner_org",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name='{self.name}', type='{self.org_type}')>"


class OrganizationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Membership record binding a User to an Organization with specific roles."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[OrgMemberRole] = mapped_column(
        SQLEnum(OrgMemberRole, name="org_member_role_enum", native_enum=False),
        nullable=False,
        default=OrgMemberRole.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="members"
    )
    user: Mapped["User"] = relationship("User", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<OrganizationMember(org_id={self.organization_id}, user_id={self.user_id}, role='{self.role}')>"


class PartnerRelationship(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Bilateral trust and operational partnership between two organizations."""

    __tablename__ = "partner_relationships"
    __table_args__ = (
        UniqueConstraint(
            "initiator_org_id", "partner_org_id", name="uq_partner_relationship"
        ),
    )

    initiator_org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    partner_org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="RECOVERY_PARTNER"
    )
    status: Mapped[PartnerStatus] = mapped_column(
        SQLEnum(PartnerStatus, name="partner_status_enum", native_enum=False),
        nullable=False,
        default=PartnerStatus.PENDING,
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    initiator_org: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[initiator_org_id],
        back_populates="outgoing_partnerships",
    )
    partner_org: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[partner_org_id],
        back_populates="incoming_partnerships",
    )

    def __repr__(self) -> str:
        return f"<PartnerRelationship(initiator={self.initiator_org_id}, partner={self.partner_org_id}, status='{self.status}')>"
