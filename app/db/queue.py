import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class QueueMessage:
    msg_id: int
    read_ct: int
    message: dict[str, Any]


class QueueRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def send(self, queue_name: str, message: dict[str, Any], delay_seconds: int = 0) -> int:
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

    async def delete(self, queue_name: str, msg_id: int) -> bool:
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
        result = await self.session.execute(
            text("select pgmq.archive(cast(:queue_name as text), cast(:msg_id as bigint))"),
            {"queue_name": queue_name, "msg_id": msg_id},
        )
        await self.session.commit()
        row = result.first()
        return bool(row[0]) if row else False
