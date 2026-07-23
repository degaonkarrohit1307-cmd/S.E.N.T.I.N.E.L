"""
DemoEchoModule -- a minimal, real module proving the v0.1 pipeline works
end to end: manifest validation -> scope registration -> load -> event
subscription -> authorization check -> publish.

This is intentionally trivial. Its only job is to be the first "real"
module other than security_manager, so registry + event bus + security
can be exercised together rather than only unit-tested in isolation.
"""
from __future__ import annotations

import logging

from domain.entities.event import Event, Priority
from domain.entities.module_manifest import ModuleManifest, SemVer
from domain.ports.module_port import HealthStatus, KernelContext, Module

logger = logging.getLogger("sentinel.modules.demo_echo")


class DemoEchoModule(Module):
    def __init__(self) -> None:
        self.manifest = ModuleManifest(
            id="demo_echo",
            version=SemVer(0, 1, 0),
            capabilities=("echo",),
            required_scopes=("demo.echo",),
            dependencies=(),
        )
        self._context: KernelContext | None = None

    async def on_load(self, context: KernelContext) -> None:
        self._context = context
        logger.info("demo_echo loaded")

    async def on_unload(self) -> None:
        logger.info("demo_echo unloaded")

    def health_check(self) -> HealthStatus:
        return HealthStatus.OK

    async def handle_event(self, event: Event) -> None:
        assert self._context is not None
        if not self._context.authorize("demo_echo", "demo.echo"):
            logger.warning("demo_echo: not authorized for demo.echo, dropping")
            return
        reply = Event(
            type="demo.echo.reply",
            source="demo_echo",
            payload={"echo": event.payload.get("text", "")},
            priority=Priority.NORMAL,
            correlation_id=event.correlation_id,
        )
        await self._context.publish(reply)
