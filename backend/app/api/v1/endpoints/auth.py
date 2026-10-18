"""PLASTIFY Authentication API Endpoints.

Implements user registration, login, token refresh, logout, profile retrieval,
password change, and account activation/deactivation.
All business logic is delegated to AuthService.
"""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status

from app.core.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    RequestIDDep,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    UserResponse,
    UserStatusUpdateRequest,
)
from app.schemas.common import APIResponse

router = APIRouter(prefix="/auth", tags=["Authentication & Access"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register New User",
    description="Registers a new user account with hashed password and initial role assignment.",
)
async def register(
    data: UserRegisterRequest,
    service: AuthServiceDep,
) -> UserResponse:
    """User registration endpoint."""
    return await service.register_user(data)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate User",
    description="Authenticates user credentials and issues JWT access and refresh token pair.",
)
async def login(
    data: UserLoginRequest,
    service: AuthServiceDep,
) -> TokenResponse:
    """User login endpoint."""
    return await service.authenticate(email=data.email, password=data.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate Refresh Token",
    description="Exchanges an active refresh token for a new access token and replacement refresh token.",
)
async def refresh_tokens(
    data: RefreshTokenRequest,
    service: AuthServiceDep,
) -> TokenResponse:
    """Token rotation endpoint."""
    return await service.refresh_tokens(data.refresh_token)


@router.post(
    "/logout",
    response_model=APIResponse[dict],
    summary="Logout User",
    description="Revokes the supplied refresh token, invalidating the session.",
)
async def logout(
    data: RefreshTokenRequest,
    service: AuthServiceDep,
    request_id: RequestIDDep,
) -> APIResponse[dict]:
    """User logout endpoint."""
    await service.logout(data.refresh_token)
    return APIResponse(
        data={"message": "Successfully logged out. Refresh token revoked."},
        request_id=request_id,
    )


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get Current User Profile",
    description="Returns the authenticated user's details and active organization membership.",
)
async def get_current_user_profile(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
) -> UserProfileResponse:
    """Retrieve profile of the currently authenticated user."""
    return await service.get_user_profile(current_user)


@router.post(
    "/change-password",
    response_model=APIResponse[dict],
    summary="Change Password",
    description="Updates user password, verifying current password and terminating other sessions.",
)
async def change_password(
    data: ChangePasswordRequest,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
    request_id: RequestIDDep,
) -> APIResponse[dict]:
    """Password update endpoint."""
    await service.change_password(
        user=current_user,
        current_password=data.current_password,
        new_password=data.new_password,
    )
    return APIResponse(
        data={"message": "Password changed successfully. All previous sessions terminated."},
        request_id=request_id,
    )


@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    summary="Update User Account Status",
    description="Activates or deactivates a user account. Restricted to Super Admins and Org Admins.",
)
async def update_user_status(
    user_id: uuid.UUID,
    data: UserStatusUpdateRequest,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
) -> UserResponse:
    """Account activation/deactivation endpoint."""
    return await service.set_user_status(
        target_user_id=user_id,
        is_active=data.is_active,
        actor=current_user,
    )
