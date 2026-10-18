"""PLASTIFY Organization, Membership, and Partnership Pydantic Schemas."""

from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.organization import (
    OrganizationType,
    OrgMemberRole,
    PartnerStatus,
)


class OrganizationCreateRequest(BaseModel):
    """Payload for registering a new organization."""

    name: str = Field(..., min_length=2, max_length=200, description="Organization legal name")
    org_type: OrganizationType = Field(..., description="Organization business type")
    contact_email: EmailStr = Field(..., description="Official contact email")
    country: str = Field(default="Global", min_length=2, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = None
    registration_number: Optional[str] = Field(default=None, max_length=100)
    tax_id: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=50)
    website: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None


class OrganizationUpdateRequest(BaseModel):
    """Payload for updating organization profile."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    contact_email: Optional[EmailStr] = None
    country: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = None
    registration_number: Optional[str] = Field(default=None, max_length=100)
    tax_id: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=50)
    website: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None


class OrganizationResponse(BaseModel):
    """Public organization profile details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    org_type: OrganizationType
    contact_email: EmailStr
    country: str
    city: Optional[str] = None
    address: Optional[str] = None
    registration_number: Optional[str] = None
    tax_id: Optional[str] = None
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class OrgMemberAddRequest(BaseModel):
    """Payload for adding or inviting a user to an organization."""

    user_id: Optional[uuid.UUID] = Field(default=None, description="Existing user ID")
    email: Optional[EmailStr] = Field(default=None, description="User email to invite/add")
    role: OrgMemberRole = Field(
        default=OrgMemberRole.MEMBER, description="Assigned organization role"
    )


class OrgMemberUpdateRequest(BaseModel):
    """Payload for modifying an organization member's role or status."""

    role: Optional[OrgMemberRole] = None
    is_active: Optional[bool] = None


class OrgMemberResponse(BaseModel):
    """Organization membership representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: OrgMemberRole
    is_active: bool
    created_at: datetime
    # User details
    user_email: Optional[str] = None
    user_name: Optional[str] = None


class PartnerCreateRequest(BaseModel):
    """Payload to initiate a partner relationship between organizations."""

    partner_org_id: uuid.UUID = Field(
        ..., description="Target partner organization ID"
    )
    relationship_type: str = Field(
        default="RECOVERY_PARTNER",
        description="Type of partnership (e.g. RECOVERY_PARTNER, VERIFICATION_PARTNER)",
    )
    notes: Optional[str] = None


class PartnerUpdateRequest(BaseModel):
    """Payload to respond to or update partnership status."""

    status: PartnerStatus = Field(..., description="Updated partner status")
    notes: Optional[str] = None


class PartnerResponse(BaseModel):
    """Organization partnership contract representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    initiator_org_id: uuid.UUID
    partner_org_id: uuid.UUID
    relationship_type: str
    status: PartnerStatus
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    initiator_name: Optional[str] = None
    partner_name: Optional[str] = None
