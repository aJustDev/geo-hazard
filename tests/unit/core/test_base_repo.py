import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampsMixin, UUIDPkMixin
from app.core.repo import BaseRepo


class WidgetORM(UUIDPkMixin, TimestampsMixin, Base):
    """Modelo minimo solo para ejercitar el repo generico."""

    __tablename__ = "test_widgets"

    name: Mapped[str] = mapped_column(nullable=False)


class WidgetRepo(BaseRepo[WidgetORM]):
    model = WidgetORM


def make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()  # add es sincrono en SQLAlchemy
    return session


async def test_create_hace_flush_y_refresh_no_commit() -> None:
    session = make_session()
    entity = WidgetORM(name="w")

    result = await WidgetRepo(session).create(entity)

    session.add.assert_called_once_with(entity)
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(entity)
    session.commit.assert_not_awaited()
    assert result is entity


async def test_get_by_id_devuelve_primero() -> None:
    session = make_session()
    sentinel = WidgetORM(name="w")
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=sentinel)))
    )

    result = await WidgetRepo(session).get_by_id(uuid.uuid4())

    assert result is sentinel


async def test_update_ignora_campos_desconocidos() -> None:
    session = make_session()
    entity = WidgetORM(name="antes")

    await WidgetRepo(session).update(entity, {"name": "despues", "inexistente": 1})

    assert entity.name == "despues"
    assert not hasattr(entity, "inexistente")
    session.flush.assert_awaited_once()


async def test_delete_borra_y_flushea() -> None:
    session = make_session()
    entity = WidgetORM(name="w")

    await WidgetRepo(session).delete(entity)

    session.delete.assert_awaited_once_with(entity)
    session.flush.assert_awaited_once()


async def test_list_paginated_devuelve_items_y_total() -> None:
    session = make_session()
    a, b = WidgetORM(name="a"), WidgetORM(name="b")
    count_result = MagicMock(scalar_one=MagicMock(return_value=3))
    items_result = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[a, b])))
    )
    session.execute.side_effect = [count_result, items_result]

    items, total = await WidgetRepo(session).list_paginated(limit=2, offset=0)

    assert items == [a, b]
    assert total == 3
