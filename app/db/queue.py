import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.interfaces import QueueStore


@dataclass(frozen=True)
class QueueMessage:
    msg_id: int
    read_ct: int
    message: dict[str, Any]


def _is_sqlite(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(bind is not None and bind.dialect.name == "sqlite")


class QueueRepository(QueueStore):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def send(self, queue_name: str, message: dict[str, Any], delay_seconds: int = 0) -> int:
        if _is_sqlite(self.session):
            now = time.time()
            result = await self.session.execute(
                text(
                    """
                    insert into queue_messages (
                      queue_name, message, read_ct, visible_at, created_at, updated_at
                    )
                    values (:queue_name, :message, 0, :visible_at, :now, :now)
                    returning id
                    """
                ),
                {
                    "queue_name": queue_name,
                    "message": json.dumps(message),
                    "visible_at": now + delay_seconds,
                    "now": now,
                },
            )
            await self.session.commit()
            row = result.first()
            return int(row[0]) if row else 0

        result = await self.session.execute(
            text(
                """
                select * from pgmq.send(
                  cast(:queue_name as text),
                  cast(:message as jsonb),
                  cast(:delay_seconds as integer)
                )
                """
            ),
            {
                "queue_name": queue_name,
                "message": json.dumps(message),
                "delay_seconds": delay_seconds,
            },
        )
        row = result.first()
        await self.session.commit()
        return int(row[0]) if row else 0

    async def read(
        self,
        queue_name: str,
        visibility_timeout_seconds: int,
        qty: int = 1,
        max_poll_seconds: int = 5,
        poll_interval_ms: int = 250,
    ) -> list[QueueMessage]:
        if _is_sqlite(self.session):
            deadline = time.monotonic() + max_poll_seconds
            while True:
                messages = await self._read_sqlite(
                    queue_name, visibility_timeout_seconds, qty
                )
                if messages or time.monotonic() >= deadline:
                    return messages
                await asyncio.sleep(poll_interval_ms / 1000)

        result = await self.session.execute(
            text(
                """
                select msg_id, read_ct, message
                from pgmq.read_with_poll(
                  cast(:queue_name as text),
                  cast(:visibility_timeout_seconds as integer),
                  cast(:qty as integer),
                  cast(:max_poll_seconds as integer),
                  cast(:poll_interval_ms as integer)
                )
                """
            ),
            {
                "queue_name": queue_name,
                "visibility_timeout_seconds": visibility_timeout_seconds,
                "qty": qty,
                "max_poll_seconds": max_poll_seconds,
                "poll_interval_ms": poll_interval_ms,
            },
        )
        rows = result.mappings().all()
        return [
            QueueMessage(
                msg_id=int(row["msg_id"]),
                read_ct=int(row["read_ct"]),
                message=row["message"]
                if isinstance(row["message"], dict)
                else json.loads(row["message"]),
            )
            for row in rows
        ]

    async def _read_sqlite(
        self,
        queue_name: str,
        visibility_timeout_seconds: int,
        qty: int,
    ) -> list[QueueMessage]:
        now = time.time()
        result = await self.session.execute(
            text(
                """
                select id, read_ct, message
                from queue_messages
                where queue_name = :queue_name
                  and archived_at is null
                  and visible_at <= :now
                order by id asc
                limit :qty
                """
            ),
            {"queue_name": queue_name, "now": now, "qty": qty},
        )
        rows = result.mappings().all()
        messages = [
            QueueMessage(
                msg_id=int(row["id"]),
                read_ct=int(row["read_ct"]) + 1,
                message=json.loads(row["message"]),
            )
            for row in rows
        ]
        for message in messages:
            await self.session.execute(
                text(
                    """
                    update queue_messages
                    set read_ct = :read_ct,
                        visible_at = :visible_at,
                        updated_at = :now
                    where id = :msg_id
                    """
                ),
                {
                    "msg_id": message.msg_id,
                    "read_ct": message.read_ct,
                    "visible_at": now + visibility_timeout_seconds,
                    "now": now,
                },
            )
        if messages:
            await self.session.commit()
        return messages

    async def delete(self, queue_name: str, msg_id: int) -> bool:
        if _is_sqlite(self.session):
            result = await self.session.execute(
                text("delete from queue_messages where queue_name = :queue_name and id = :msg_id"),
                {"queue_name": queue_name, "msg_id": msg_id},
            )
            await self.session.commit()
            return bool(result.rowcount)

        result = await self.session.execute(
            text("select pgmq.delete(cast(:queue_name as text), cast(:msg_id as bigint))"),
            {"queue_name": queue_name, "msg_id": msg_id},
        )
        await self.session.commit()
        row = result.first()
        return bool(row[0]) if row else False

    async def set_vt(
        self, queue_name: str, msg_id: int, visibility_timeout_seconds: int
    ) -> QueueMessage | None:
        if _is_sqlite(self.session):
            now = time.time()
            result = await self.session.execute(
                text(
                    """
                    update queue_messages
                    set visible_at = :visible_at,
                        updated_at = :now
                    where queue_name = :queue_name
                      and id = :msg_id
                      and archived_at is null
                    returning id, read_ct, message
                    """
                ),
                {
                    "queue_name": queue_name,
                    "msg_id": msg_id,
                    "visible_at": now + visibility_timeout_seconds,
                    "now": now,
                },
            )
            await self.session.commit()
            row = result.mappings().first()
            if not row:
                return None
            return QueueMessage(
                msg_id=int(row["id"]),
                read_ct=int(row["read_ct"]),
                message=json.loads(row["message"]),
            )

        result = await self.session.execute(
            text(
                """
                select msg_id, read_ct, message
                from pgmq.set_vt(
                  cast(:queue_name as text),
                  cast(:msg_id as bigint),
                  cast(:visibility_timeout_seconds as integer)
                )
                """
            ),
            {
                "queue_name": queue_name,
                "msg_id": msg_id,
                "visibility_timeout_seconds": visibility_timeout_seconds,
            },
        )
        await self.session.commit()
        row = result.mappings().first()
        if not row:
            return None
        return QueueMessage(
            msg_id=int(row["msg_id"]),
            read_ct=int(row["read_ct"]),
            message=(
                row["message"]
                if isinstance(row["message"], dict)
                else json.loads(row["message"])
            ),
        )

    async def archive(self, queue_name: str, msg_id: int) -> bool:
        if _is_sqlite(self.session):
            now = time.time()
            result = await self.session.execute(
                text(
                    """
                    update queue_messages
                    set archived_at = :now,
                        updated_at = :now
                    where queue_name = :queue_name and id = :msg_id
                    """
                ),
                {"queue_name": queue_name, "msg_id": msg_id, "now": now},
            )
            await self.session.commit()
            return bool(result.rowcount)

        result = await self.session.execute(
            text("select pgmq.archive(cast(:queue_name as text), cast(:msg_id as bigint))"),
            {"queue_name": queue_name, "msg_id": msg_id},
        )
        await self.session.commit()
        row = result.first()
        return bool(row[0]) if row else False
