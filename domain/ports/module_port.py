"""
Domain port: Module

The interface every S.E.N.T.I.N.E.L. module implements (SAD Part 4.1).
Application/Infrastructure code depends on THIS abstraction, never on a
concrete module class directly -- that's what keeps every module
independently replaceable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from domain.entities.event import Event
from domain.entities.module_manifest import ModuleManifest


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class KernelContext(ABC):
    """
    What the kernel hands to a module on load: a scoped handle to publish
    events and request authorization. A module never reaches into the
    kernel or other modules directly.
    """

    @abstractmethod
    async def publish(self, event: Event) -> None:
        ...

    @abstractmethod
    def authorize(self, module_id: str, scope: str) -> bool:
        ...


class Module(ABC):
    manifest: ModuleManifest

    @abstractmethod
    async def on_load(self, context: KernelContext) -> None:
        """Called once, after manifest validation and scope authorization
        succeed. Module should subscribe to any events it needs here."""

    @abstractmethod
    async def on_unload(self) -> None:
        """Called on graceful shutdown or hot-reload replacement."""

    @abstractmethod
    def health_check(self) -> HealthStatus:
        ...

    async def handle_event(self, event: Event) -> None:
        """Default no-op. Override if the module subscribes to events."""
        return None
