"""Process-wide pub/sub for SSE notifications.

Single-instance only — when scaling out to multiple uvicorn workers/replicas,
swap the in-memory hub for Redis pub/sub (or similar). Each SSE subscriber
gets a bounded asyncio.Queue; the email reader publishes to whichever
hospital's subscribers are currently listening.

Thread-safety: the email scheduler runs in a background thread (APScheduler),
while FastAPI handlers run on the main asyncio loop. `publish_threadsafe`
hops onto the loop using `asyncio.run_coroutine_threadsafe` so the queue
update happens in the right context.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Per-subscriber queue size. If a client lags this far behind, we drop the
# oldest event rather than growing memory unbounded — the client still gets a
# fresh state on its next poll/page navigation.
_QUEUE_MAXSIZE = 32


class EventHub:
    def __init__(self) -> None:
        # hospital_id (str) -> list of subscriber queues
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once on app startup so background threads can dispatch
        back onto the FastAPI event loop."""
        self._loop = loop

    async def subscribe(self, hospital_id: UUID | str) -> asyncio.Queue:
        key = str(hospital_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.setdefault(key, []).append(queue)
        return queue

    async def unsubscribe(self, hospital_id: UUID | str, queue: asyncio.Queue) -> None:
        key = str(hospital_id)
        async with self._lock:
            queues = self._subscribers.get(key, [])
            if queue in queues:
                queues.remove(queue)
            if not queues and key in self._subscribers:
                self._subscribers.pop(key, None)

    async def _publish_async(self, hospital_id: UUID | str, event: dict[str, Any]) -> None:
        key = str(hospital_id)
        # Snapshot list under the lock so concurrent (un)subscribe doesn't
        # mutate while we iterate.
        async with self._lock:
            queues = list(self._subscribers.get(key, []))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer — drop the oldest, push the new. Better to lose
                # one stale event than block the publisher.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    def publish_threadsafe(self, hospital_id: UUID | str, event: dict[str, Any]) -> None:
        """Safe to call from any thread, including the APScheduler worker.

        Returns immediately; publication happens on the event loop. Any error
        is swallowed and logged — publishes must never fail business work.
        """
        if self._loop is None:
            # App hasn't bound the loop yet (very early startup). Silently
            # drop — the email reader runs every 2 min so we'll catch up soon.
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._publish_async(hospital_id, event),
                self._loop,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"event_hub publish failed (non-fatal): {e}")


# Singleton — imported by both the SSE route and the email reader.
event_hub = EventHub()
