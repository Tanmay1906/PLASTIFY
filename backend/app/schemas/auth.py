"""PLASTIFY Authentication and User Pydantic Schemas."""

from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegisterRequest(BaseModel):
    """Payload for registering a new user account."""

    email: EmailStr = Field(..., description="Unique email address")
    password: str = Field(..., min_length=8, max_length=72, description="Password (min 8 chars)")
    first_name: str = Field(..., min_length=1, max_length=100, description="First name")
    last_name: str = Field(..., min_length=1, max_length=100, description="Last name")
    role: Optional[UserRole] = Field(
        default=UserRole.CORPORATE, description="Requested platform role"
    )
    organization_id: Optional[uuid.UUID] = Field(
        default=None, description="Optional organization ID to join"
    )


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., min_length=1, max_length=72, description="Password")


class TokenResponse(BaseModel):
    """JWT Access and Refresh token pair."""

    access_token: str = Field(..., description="JWT bearer access token")
    refresh_token: str = Field(..., description="Opaque or JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration window in seconds")


class RefreshTokenRequest(BaseModel):
    """Payload to exchange a refresh token for new access and refresh tokens."""

    refresh_token: str = Field(..., description="Valid refresh token")


class ChangePasswordRequest(BaseModel):
    """Payload for updating user password."""

    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(
        ..., min_length=8, max_length=72, description="New password (min 8 chars)"
    )


class UserStatusUpdateRequest(BaseModel):
    """Payload for activating or deactivating a user account."""

    is_active: bool = Field(..., description="New activation state")


class UserResponse(BaseModel):
    """Public user account details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    full_name: str
    role: UserRole
    organization_id: Optional[uuid.UUID] = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class UserProfileResponse(BaseModel):
    """Detailed profile representation including organization summary."""

    model_config = ConfigDict(from_attributes=True)

    user: UserResponse
    organization_name: Optional[str] = None
    organization_type: Optional[str] = None
    organization_role: Optional[str] = None
