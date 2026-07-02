import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base


class BaseRepo[T: Base]:
    """Async generic repository.

    Repos flush()+refresh() but never commit: the request session (get_session)
    or the worker that owns the session decides the transaction boundary.
    """

    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def get_by_id(self, entity_id: uuid.UUID) -> T | None:
        stmt = select(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update(self, entity: T, data: dict[str, Any]) -> T:
        for key, value in data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def list_paginated(self, *, limit: int = 50, offset: int = 0) -> tuple[list[T], int]:
        total = (
            await self.session.execute(select(func.count()).select_from(self.model))
        ).scalar_one()
        items = list(
            (
                await self.session.execute(
                    select(self.model).order_by(self.model.id).offset(offset).limit(limit)  # type: ignore[attr-defined]
                )
            )
            .scalars()
            .all()
        )
        return items, total
