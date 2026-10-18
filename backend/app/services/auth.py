"""PLASTIFY Authentication Business Service.

Coordinates user registration, credential verification, JWT token lifecycle,
refresh token rotation/revocation, password management, and profile retrieval.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.organization import OrgMemberRole
from app.models.user import User, UserRole
from app.repositories.organization import OrganizationRepository, OrgMemberRepository
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.schemas.auth import (
    TokenResponse,
    UserProfileResponse,
    UserRegisterRequest,
    UserResponse,
)
from app.services.base import BaseService


class AuthService(BaseService):
    """Core domain service managing user authentication and identity."""

    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        token_repo: RefreshTokenRepository,
        org_repo: OrganizationRepository,
        org_member_repo: OrgMemberRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.user_repo = user_repo
        self.token_repo = token_repo
        self.org_repo = org_repo
        self.org_member_repo = org_member_repo

    async def register_user(self, data: UserRegisterRequest) -> UserResponse:
        """Register a new user account with hashed credentials."""
        # 1. Enforce unique email address
        existing_user = await self.user_repo.get_by_email(data.email)
        if existing_user:
            raise ConflictException(f"User with email '{data.email}' already exists.")

        # 2. Validate organization if provided
        if data.organization_id:
            org = await self.org_repo.get_by_id(data.organization_id)
            if not org or not org.is_active:
                raise NotFoundException("Specified organization does not exist or is inactive.")

        # 3. Create user with hashed password
        hashed_pwd = hash_password(data.password)
        user = User(
            email=data.email.strip().lower(),
            hashed_password=hashed_pwd,
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            role=data.role or UserRole.CORPORATE,
            organization_id=data.organization_id,
            is_active=True,
            is_verified=False,
        )
        created_user = await self.user_repo.create(user)

        # 4. If organization provided, create membership
        if data.organization_id:
            from app.models.organization import OrganizationMember

            membership = OrganizationMember(
                organization_id=data.organization_id,
                user_id=created_user.id,
                role=OrgMemberRole.MEMBER,
                is_active=True,
            )
            await self.org_member_repo.create(membership)

        self.logger.info(
            f"User registered successfully: {created_user.email}",
            extra={"user_id": str(created_user.id), "role": created_user.role.value},
        )
        return UserResponse.model_validate(created_user)

    async def authenticate(self, email: str, password: str) -> TokenResponse:
        """Authenticate user by email and password, issuing access & refresh token pair."""
        user = await self.user_repo.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            self.logger.warning(f"Failed login attempt for email: {email}")
            raise UnauthorizedException("Invalid email or password.")

        if not user.is_active:
            self.logger.warning(f"Login denied for inactive user: {user.email}")
            raise ForbiddenException("Account has been deactivated. Please contact support.")

        # Update last login timestamp
        await self.user_repo.update_last_login(user)

        # Generate tokens
        return await self._generate_token_pair(user)

    async def refresh_tokens(self, refresh_token_str: str) -> TokenResponse:
        """Rotate a refresh token, issuing a fresh access token and replacement refresh token."""
        # 1. Decode and cryptographically verify refresh token
        payload = decode_token(refresh_token_str, expected_type="refresh")
        user_id_str = payload.get("sub")
        family_id = payload.get("family")

        if not user_id_str or not family_id:
            raise UnauthorizedException("Malformed refresh token payload.")

        # 2. Check token in database by digest
        token_digest = hash_token(refresh_token_str)
        stored_token = await self.token_repo.get_by_hash(token_digest)

        if not stored_token:
            raise UnauthorizedException("Refresh token is unrecognized or expired.")

        # 3. Security: Check for replay of revoked token (token theft mitigation)
        if stored_token.is_revoked:
            self.logger.warning(
                f"Replay attack detected on token family {family_id}. Revoking all sessions for user {user_id_str}."
            )
            await self.token_repo.revoke_family(family_id)
            raise UnauthorizedException(
                "Revoked refresh token re-used. All active sessions in family terminated for security."
            )

        # 4. Check expiration
        now = datetime.now(timezone.utc)
        if stored_token.expires_at.replace(tzinfo=timezone.utc) < now:
            await self.token_repo.revoke(stored_token)
            raise UnauthorizedException("Refresh token has expired. Please log in again.")

        # 5. Load and check user status
        user = await self.user_repo.get_by_id(stored_token.user_id)
        if not user or not user.is_active:
            await self.token_repo.revoke(stored_token)
            raise UnauthorizedException("Associated user account is invalid or inactive.")

        # 6. ROTATION: Invalidate the used refresh token
        await self.token_repo.revoke(stored_token)

        # 7. Issue new tokens preserving the token family
        return await self._generate_token_pair(user, token_family=family_id)

    async def logout(self, refresh_token_str: str) -> None:
        """Revoke a refresh token on logout."""
        try:
            token_digest = hash_token(refresh_token_str)
            stored_token = await self.token_repo.get_by_hash(token_digest)
            if stored_token:
                await self.token_repo.revoke(stored_token)
                self.logger.info(f"Revoked refresh token for user {stored_token.user_id}")
        except Exception as exc:
            self.logger.debug(f"Logout token revocation encountered: {exc}")

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        """Change user password, verifying current password and revoking active sessions."""
        if not verify_password(current_password, user.hashed_password):
            raise BadRequestException("Current password provided is incorrect.")

        if verify_password(new_password, user.hashed_password):
            raise BadRequestException("New password cannot be identical to current password.")

        user.hashed_password = hash_password(new_password)
        await self.user_repo.session.flush()

        # Revoke all existing sessions so old tokens cannot be used
        await self.token_repo.revoke_user_tokens(user.id)
        self.logger.info(f"Password changed for user {user.email}. All sessions revoked.")

    async def set_user_status(
        self, target_user_id: uuid.UUID, is_active: bool, actor: User
    ) -> UserResponse:
        """Activate or deactivate user account."""
        target_user = await self.user_repo.get_by_id(target_user_id)
        if not target_user:
            raise NotFoundException("User not found.")

        # Authorization: actor must be SUPER_ADMIN or Org ADMIN of target user's org
        is_super = actor.role == UserRole.SUPER_ADMIN
        is_org_admin = (
            actor.organization_id is not None
            and actor.organization_id == target_user.organization_id
            and await self.org_member_repo.is_org_admin(actor.organization_id, actor.id)
        )

        if not is_super and not is_org_admin:
            raise ForbiddenException("Insufficient permissions to modify user account status.")

        target_user.is_active = is_active
        await self.user_repo.session.flush()

        if not is_active:
            # Terminate all active sessions upon deactivation
            await self.token_repo.revoke_user_tokens(target_user.id)

        self.logger.info(
            f"User {target_user.email} activation status set to {is_active} by {actor.email}"
        )
        return UserResponse.model_validate(target_user)

    async def get_user_profile(self, user: User) -> UserProfileResponse:
        """Build user profile with organization membership details."""
        user_with_org = await self.user_repo.get_with_organization(user.id)
        current_user = user_with_org or user

        org_name = None
        org_type = None
        org_role = None

        if current_user.organization_id:
            if current_user.organization:
                org_name = current_user.organization.name
                org_type = current_user.organization.org_type.value

            membership = await self.org_member_repo.get_membership(
                current_user.organization_id, current_user.id
            )
            if membership:
                org_role = membership.role.value

        return UserProfileResponse(
            user=UserResponse.model_validate(current_user),
            organization_name=org_name,
            organization_type=org_type,
            organization_role=org_role,
        )

    async def _generate_token_pair(
        self, user: User, token_family: Optional[str] = None
    ) -> TokenResponse:
        """Internal helper to mint an access token and persisted refresh token."""
        access_claims = {
            "email": user.email,
            "role": user.role.value,
            "org_id": str(user.organization_id) if user.organization_id else None,
        }
        access_token = create_access_token(subject=user.id, claims=access_claims)

        raw_refresh, family_id, expires_at = create_refresh_token(
            subject=user.id, token_family=token_family
        )

        # Store SHA-256 digest of refresh token in database
        token_digest = hash_token(raw_refresh)
        await self.token_repo.create_token(
            user_id=user.id,
            token_hash=token_digest,
            token_family=family_id,
            expires_at=expires_at,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            token_type="bearer",
            expires_in=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
