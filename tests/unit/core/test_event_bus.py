from unittest.mock import AsyncMock, MagicMock

from app.core.events.bus import EventBus
from app.core.events.models import OutboxEventORM


async def test_publish_inserta_sin_commit() -> None:
    session = AsyncMock()
    session.add = MagicMock()

    event = await EventBus(session).publish("test.evento", {"k": 1})

    added = session.add.call_args.args[0]
    assert isinstance(added, OutboxEventORM)
    assert added.event_type == "test.evento"
    assert added.payload == {"k": 1}
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.execute.assert_not_awaited()
    assert event is added
