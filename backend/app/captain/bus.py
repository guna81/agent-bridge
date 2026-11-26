"""In-process pub/sub event bus for live Captain mission streams and notifications."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import AsyncIterator

from ..models import iso_utc, utcnow


@dataclass
class NotificationEvent:
    id: int
    kind: str  # awaiting_approval | needs_input | completed | failed | cancelled | info
    project_id: int
    project_name: str
    mission_id: str
    task_id: int | None
    title: str
    body: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class MissionEventBus:
    """Async fan-out event bus feeding Dashboard SSE, CLI streams, and tray alerts."""

    def __init__(self, max_notifications: int = 50):
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._notifications: deque[NotificationEvent] = deque(maxlen=max_notifications)
        self._next_notif_id = 1
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Signal all active SSE subscribers to exit cleanly (prevents reload/shutdown hangs)."""
        self._closed = True
        for group in list(self._subscribers.values()):
            for q in list(group):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    def publish(self, mission_id: str, event: str, data: dict) -> None:
        payload = {"event": event, "mission_id": mission_id, "data": data, "ts": iso_utc(utcnow())}
        for key in (mission_id, "*"):
            for q in list(self._subscribers.get(key, ())):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    def record_notification(
        self,
        *,
        kind: str,
        project_id: int,
        project_name: str,
        mission_id: str,
        title: str,
        body: str,
        task_id: int | None = None,
    ) -> NotificationEvent:
        notif = NotificationEvent(
            id=self._next_notif_id,
            kind=kind,
            project_id=project_id,
            project_name=project_name,
            mission_id=mission_id,
            task_id=task_id,
            title=title,
            body=body,
            created_at=iso_utc(utcnow()) or "",
        )
        self._next_notif_id += 1
        self._notifications.append(notif)
        self.publish(mission_id, "notification", notif.to_dict())
        return notif

    def recent_notifications(self, since_id: int = 0) -> list[dict]:
        return [n.to_dict() for n in self._notifications if n.id > since_id]

    @asynccontextmanager
    async def subscribe(self, mission_id: str | None = None) -> AsyncIterator[asyncio.Queue]:
        key = mission_id or "*"
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(key, set()).add(q)
        try:
            yield q
        finally:
            subs = self._subscribers.get(key)
            if subs:
                subs.discard(q)
                if not subs:
                    self._subscribers.pop(key, None)
