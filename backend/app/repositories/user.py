"""PLASTIFY User and Refresh Token Repositories."""

from datetime import datetime, timezone
from typing import List, Optional
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import RefreshToken, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data access repository for User entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Fetch user by lowercase email address."""
        stmt = (
            select(User)
            .where(User.email == email.strip().lower())
            .options(selectinload(User.organization))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_with_organization(self, user_id: uuid.UUID) -> Optional[User]:
        """Fetch user with eager-loaded organization."""
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.organization))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_last_login(self, user: User) -> User:
        """Record last login timestamp for the user."""
        user.last_login_at = datetime.now(timezone.utc)
        await self.session.flush()
        return user


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Data access repository for refresh token validation, rotation, and revocation."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RefreshToken, session)

    async def create_token(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        token_family: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Create and store a hashed refresh token."""
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            token_family=token_family,
            expires_at=expires_at,
            is_revoked=False,
        )
        return await self.create(token)

    async def get_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        """Fetch a refresh token record by its digest."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def revoke(self, token: RefreshToken) -> None:
        """Revoke a single refresh token."""
        token.is_revoked = True
        await self.session.flush()

    async def revoke_family(self, token_family: str) -> None:
        """Revoke all tokens in a family (compromise/reuse mitigation)."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.token_family == token_family)
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def revoke_user_tokens(self, user_id: uuid.UUID) -> None:
        """Revoke all active tokens for a specific user (global logout)."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)
        await self.session.flush()
