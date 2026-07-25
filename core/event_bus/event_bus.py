"""
AsyncEventBus -- in-process pub/sub with three priority lanes.

Design (SAD Part 3.5, 3.6):
  - critical: processed immediately by a dedicated worker, can starve
    lower lanes briefly by design (e.g. a security alert must win)
  - high: low-latency FIFO (active conversation turn)
  - normal: batched, backpressure-aware (background writes, research)

Each subscribed handler runs inside a circuit breaker: three consecutive
exceptions disable that handler and emit `system.module.error` rather
than ever crashing the bus itself.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from domain.entities.event import Event, Priority
from domain.ports.system_ports import EventBusPort, EventHandler

logger = logging.getLogger("sentinel.event_bus")

_QUEUE_MAXSIZE_NORMAL = 1000
_MAX_CONSECUTIVE_FAILURES = 3


class _CircuitBreaker:
    def __init__(self, max_failures: int = _MAX_CONSECUTIVE_FAILURES):
        self.max_failures = max_failures
        self.consecutive_failures = 0
        self.tripped = False

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> bool:
        """Returns True if this failure just tripped the breaker."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures and not self.tripped:
            self.tripped = True
            return True
        return False


class _Subscription:
    """Pairs a handler with its own circuit breaker as a single owned
    object, rather than keying a side-table by id(handler) (v0.1.1 fix:
    id() is only unique for an object's lifetime and can be silently
    reused after garbage collection -- see ADR-0002)."""

    __slots__ = ("handler", "breaker")

    def __init__(self, handler: EventHandler) -> None:
        self.handler = handler
        self.breaker = _CircuitBreaker()


class AsyncEventBus(EventBusPort):
    def __init__(self, normal_queue_maxsize: int = _QUEUE_MAXSIZE_NORMAL) -> None:
        """
        `normal_queue_maxsize` defaults to the original hardcoded constant,
        so existing callers (`AsyncEventBus()`) are unaffected. v0.2 wires
        this from the Configuration Manager's `event_bus.queue_size` key
        via the Kernel; nothing about this constructor's default behavior
        changed.
        """
        self._subscribers: dict[str, list[_Subscription]] = defaultdict(list)
        self._queues: dict[Priority, asyncio.Queue] = {
            Priority.CRITICAL: asyncio.Queue(),
            Priority.HIGH: asyncio.Queue(),
            Priority.NORMAL: asyncio.Queue(maxsize=normal_queue_maxsize),
        }
        self._dead_letters: list[Event] = []
        self._workers: list[asyncio.Task] = []
        self._running = False

    # -- EventBusPort ---------------------------------------------------

    async def publish(self, event: Event) -> None:
        queue = self._queues[event.priority]
        if event.priority is Priority.NORMAL and queue.full():
            # Backpressure: drop-oldest rather than block the publisher
            # or grow memory unboundedly on a flood of low-priority events.
            _ = queue.get_nowait()
            logger.warning("normal-priority queue full, dropped oldest event")
        await queue.put(event)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(_Subscription(handler))

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        subs = self._subscribers.get(event_type, [])
        self._subscribers[event_type] = [s for s in subs if s.handler != handler]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # One dedicated worker per lane keeps critical events from ever
        # waiting behind a backlog of normal-priority work.
        self._workers = [
            asyncio.create_task(self._worker_loop(Priority.CRITICAL)),
            asyncio.create_task(self._worker_loop(Priority.HIGH)),
            asyncio.create_task(self._worker_loop(Priority.NORMAL)),
        ]
        logger.info("event bus started (3 lanes)")

    async def stop(self) -> None:
        self._running = False
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        logger.info("event bus stopped")

    # -- internals --------------------------------------------------------

    async def _worker_loop(self, priority: Priority) -> None:
        queue = self._queues[priority]
        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            await self._dispatch(event)

    async def _dispatch(self, event: Event) -> None:
        subs = list(self._subscribers.get(event.type, []))
        if not subs:
            return
        # v0.1.1 fix: an event is appended to the dead-letter queue at
        # most once per dispatch, regardless of how many handlers fail on
        # it (previously duplicated once per failing handler).
        any_handler_failed = False
        for sub in subs:
            if sub.breaker.tripped:
                continue
            try:
                await sub.handler(event)
                sub.breaker.record_success()
            except Exception:  # noqa: BLE001 -- isolate handler faults
                any_handler_failed = True
                logger.exception(
                    "handler failed for event_type=%s event_id=%s",
                    event.type,
                    event.event_id,
                )
                if sub.breaker.record_failure():
                    logger.error(
                        "circuit breaker tripped for a handler of %s "
                        "-- disabling it, emitting system.module.error",
                        event.type,
                    )
                    await self.publish(
                        Event(
                            type="system.module.error",
                            source="event_bus",
                            payload={"failed_event_type": event.type},
                            priority=Priority.HIGH,
                        )
                    )
        if event.requires_ack and any_handler_failed:
            self._dead_letters.append(event)

    def dead_letters(self) -> list[Event]:
        """Exposed for the Logs/Diagnostics UI (SAD Part 3.6, 7.3)."""
        return list(self._dead_letters)
