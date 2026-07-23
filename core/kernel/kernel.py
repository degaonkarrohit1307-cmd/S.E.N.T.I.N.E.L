"""
Kernel -- the boot sequence (SAD Part 2.2, "Core Engine").

Boot order matters and is intentionally rigid:
  1. Event Bus       (nothing can communicate before this exists)
  2. Security Manager (must exist before any module registers scopes)
  3. Module Registry  (needs both of the above to validate + wire modules)

This file has no knowledge of what modules exist -- that's the whole
point of the registry pattern. main.py decides what to load.
"""
from __future__ import annotations

import logging

from core.event_bus.event_bus import AsyncEventBus
from core.module_registry.registry import ModuleRegistry
from domain.entities.event import Event
from domain.ports.module_port import KernelContext
from domain.ports.system_ports import SecurityPort

logger = logging.getLogger("sentinel.kernel")


class _KernelContextImpl(KernelContext):
    def __init__(self, event_bus: AsyncEventBus, security: SecurityPort) -> None:
        self._event_bus = event_bus
        self._security = security

    async def publish(self, event: Event) -> None:
        await self._event_bus.publish(event)

    def authorize(self, module_id: str, scope: str) -> bool:
        return self._security.authorize(module_id, scope)


class Kernel:
    def __init__(self, security: SecurityPort) -> None:
        self.event_bus = AsyncEventBus()
        self.security = security
        self.context = _KernelContextImpl(self.event_bus, self.security)
        self.registry = ModuleRegistry(self.security, self.context)

    async def start(self) -> None:
        logger.info("kernel starting")
        await self.event_bus.start()
        await self.event_bus.publish(
            Event(type="system.kernel.started", source="core")
        )
        logger.info("kernel started")

    async def stop(self) -> None:
        logger.info("kernel stopping")
        for module_id in list(self.registry.all_manifests().keys()):
            await self.registry.unload(module_id)
        await self.event_bus.stop()
        logger.info("kernel stopped")
