"""Notification & communication channel dispatcher (EventBus + Outbound Webhooks)."""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx

from ..logging_setup import log
from .bus import MissionEventBus, NotificationEvent


def format_webhook_payload(url: str, notif: NotificationEvent) -> tuple[dict | str, dict[str, str]]:
    """Auto-format webhook payloads for Discord, Slack, ntfy, or generic JSON endpoints."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    prefix = f"[{notif.project_name}] {notif.title}"

    if "discord.com" in host or "discordapp.com" in host:
        return {"content": f"**{prefix}**\n{notif.body}"}, {"Content-Type": "application/json"}
    if "hooks.slack.com" in host or "slack.com" in host and "/services/" in path:
        return {"text": f"*{prefix}*\n{notif.body}"}, {"Content-Type": "application/json"}
    if "ntfy.sh" in host or host.startswith("ntfy."):
        return notif.body or notif.title, {"Title": prefix, "Tags": "robot"}
    return {
        "event": notif.kind,
        "project_id": notif.project_id,
        "project": notif.project_name,
        "mission_id": notif.mission_id,
        "task_id": notif.task_id,
        "title": notif.title,
        "body": notif.body,
        "created_at": notif.created_at,
    }, {"Content-Type": "application/json"}


class ChannelDispatcher:
    """Delivers Captain notifications to the live event bus and optional project webhooks."""

    def __init__(self, bus: MissionEventBus, transport: httpx.AsyncBaseTransport | None = None):
        self.bus = bus
        self.transport = transport
        self._pending: set[asyncio.Task] = set()

    def notify(
        self,
        *,
        kind: str,
        project_id: int,
        project_name: str,
        mission_id: str,
        title: str,
        body: str,
        task_id: int | None = None,
        webhook_url: str = "",
        webhook_events: list[str] | None = None,
    ) -> NotificationEvent:
        notif = self.bus.record_notification(
            kind=kind,
            project_id=project_id,
            project_name=project_name,
            mission_id=mission_id,
            task_id=task_id,
            title=title,
            body=body,
        )
        allowed = webhook_events if webhook_events is not None else ["awaiting_approval", "needs_input", "completed", "failed"]
        if webhook_url and webhook_url.strip() and kind in allowed:
            task = asyncio.create_task(self._send_webhook_safe(webhook_url.strip(), notif))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
        return notif

    async def _send_webhook_safe(self, url: str, notif: NotificationEvent) -> None:
        try:
            await self.deliver_webhook(url, notif)
        except Exception as exc:
            log("captain.webhook_failed", url_host=urlparse(url).hostname or "", error=str(exc))

    async def deliver_webhook(self, url: str, notif: NotificationEvent) -> int:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Webhook URL must use http:// or https://")
        payload, headers = format_webhook_payload(url, notif)
        async with httpx.AsyncClient(timeout=8.0, transport=self.transport) as client:
            if isinstance(payload, str):
                resp = await client.post(url, content=payload.encode("utf-8"), headers=headers)
            else:
                resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.status_code

    async def shutdown(self) -> None:
        for t in list(self._pending):
            t.cancel()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
