"""
Domain ports: EventBusPort, SecurityPort

Interfaces for the two subsystems every module depends on (SAD Part 2.2:
"the Core Engine and Security Manager are the only modules every other
module is permitted to depend on directly"). Infrastructure provides the
concrete implementations; nothing above this layer knows or cares how.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from domain.entities.event import Event

EventHandler = Callable[[Event], Awaitable[None]]


class EventBusPort(ABC):
    @abstractmethod
    async def publish(self, event: Event) -> None:
        ...

    @abstractmethod
    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        ...

    @abstractmethod
    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...


class SecurityPort(ABC):
    @abstractmethod
    def authorize(self, module_id: str, scope: str) -> bool:
        """Returns True only if module_id declared `scope` in its manifest
        AND that scope is currently granted (SAD Part 6.2)."""

    @abstractmethod
    def register_module_scopes(self, module_id: str, declared_scopes: tuple[str, ...]) -> None:
        """Called by the registry at load time -- a module can never be
        authorized for a scope it didn't declare up front."""

    @abstractmethod
    def audit(self, module_id: str, scope: str, granted: bool, reason: str = "") -> None:
        """Append-only audit trail (SAD Part 6.6)."""
