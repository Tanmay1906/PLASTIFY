"""PLASTIFY Generic Repository Pattern.

Abstracts database access and query logic away from the service layer.
"""

from typing import Any, Generic, List, Optional, Type, TypeVar
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic base repository providing type-safe CRUD operations."""

    def __init__(self, model_class: Type[ModelT], session: AsyncSession) -> None:
        self.model_class = model_class
        self.session = session

    async def get_by_id(self, id_val: Any) -> Optional[ModelT]:
        """Fetch a single record by primary key."""
        return await self.session.get(self.model_class, id_val)

    async def list(self, skip: int = 0, limit: int = 100) -> List[ModelT]:
        """Fetch a paginated list of records ordered by created_at desc if available."""
        query = select(self.model_class)
        if hasattr(self.model_class, "created_at"):
            query = query.order_by(getattr(self.model_class, "created_at").desc())
        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, instance: ModelT) -> ModelT:
        """Add and flush a new record to the session."""
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Delete a record from the database."""
        await self.session.delete(instance)
        await self.session.flush()

    async def count(self) -> int:
        """Return total count of records for the entity."""
        query = select(func.count()).select_from(self.model_class)
        result = await self.session.execute(query)
        return int(result.scalar_one())
