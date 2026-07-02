from unittest.mock import AsyncMock

from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPkMixin
from app.core.repo import BaseRepo
from app.deps.repository import get_repo


class GadgetORM(UUIDPkMixin, Base):
    """Modelo minimo solo para ejercitar la factory de providers."""

    __tablename__ = "test_gadgets"

    name: Mapped[str] = mapped_column(nullable=False)


class GadgetRepo(BaseRepo[GadgetORM]):
    model = GadgetORM


async def test_get_repo_construye_el_repo_con_la_sesion() -> None:
    provider = get_repo(GadgetRepo)
    session = AsyncMock()

    repo = await provider(session=session)

    assert isinstance(repo, GadgetRepo)
    assert repo.session is session
