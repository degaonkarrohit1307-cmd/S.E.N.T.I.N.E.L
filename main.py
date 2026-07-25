"""
S.E.N.T.I.N.E.L. v0.1 -- Core Engine boot demo.

Run with:  python main.py

This proves the v0.1 slice end to end:
  manifest load -> scope registration -> module load ->
  event publish -> authorization check -> reply event -> audit log written

Nothing here is meant to be the "real" product yet -- v0.2 replaces this
demo with the actual Memory Engine + CLI (SAD Part 10).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from core.config_manager.src.config_manager import ConfigurationManager
from core.config_manager.src.sources import (
    EnvVarConfigSource,
    JsonFileConfigSource,
    YamlFileConfigSource,
)
from core.kernel.kernel import Kernel
from domain.entities.event import Event
from modules.demo_echo.src.demo_echo import DemoEchoModule
from modules.security_manager.src.security_manager import SecurityManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ROOT = Path(__file__).parent


async def main() -> None:
    # Precedence, lowest to highest: default.json -> local.yaml -> env vars
    config = ConfigurationManager(
        sources=[
            JsonFileConfigSource(ROOT / "core" / "config" / "default.json"),
            YamlFileConfigSource(ROOT / "core" / "config" / "local.yaml"),
            EnvVarConfigSource(),
        ]
    )

    security = SecurityManager(
        granted_scopes_path=ROOT / config.get_str(
            "security.granted_scopes_path", "core/config/granted_scopes.json"
        ),
        audit_log_path=ROOT / config.get_str(
            "security.audit_log_path", "core/config/audit.log"
        ),
    )
    kernel = Kernel(security=security, config=config)
    await kernel.start()

    demo = DemoEchoModule()
    kernel.registry.load_manifest(ROOT / "modules" / "demo_echo" / "module.manifest.json")
    await kernel.registry.load(demo)
    kernel.event_bus.subscribe("demo.echo.request", demo.handle_event)

    replies: list[Event] = []

    async def on_reply(event: Event) -> None:
        replies.append(event)
        print(f"[reply] {event.payload}")

    kernel.event_bus.subscribe("demo.echo.reply", on_reply)

    await kernel.event_bus.publish(
        Event(type="demo.echo.request", source="main", payload={"text": "hello, sentinel"})
    )

    # give the async worker loop a moment to process the queued event
    await asyncio.sleep(0.2)

    await kernel.stop()

    print(f"\naudit log written to: {security._audit_log_path}")
    print(f"replies received: {len(replies)}")
    print(f"config loaded (event_bus.queue_size={config.get_int('event_bus.queue_size')})")


if __name__ == "__main__":
    asyncio.run(main())
