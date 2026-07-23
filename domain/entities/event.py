"""
Domain entity: Event

Pure dataclass with zero framework dependency (no asyncio, no DB, no I/O).
This is the envelope every module communicates through, as defined in
SAD Part 3.2.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"


@dataclass(frozen=True)
class Event:
    type: str                                  # e.g. "voice.transcript.final"
    source: str                                # module id that emitted it
    payload: dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    requires_ack: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def with_correlation(self, correlation_id: str) -> "Event":
        """Return a copy of this event tagged with a correlation id.

        Used when one event triggers another, so the whole causal chain
        can be traced through the audit/debug logs (SAD Part 3.2, 6.6).
        """
        return Event(
            type=self.type,
            source=self.source,
            payload=self.payload,
            priority=self.priority,
            correlation_id=correlation_id,
            requires_ack=self.requires_ack,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority.value,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "requires_ack": self.requires_ack,
        }
