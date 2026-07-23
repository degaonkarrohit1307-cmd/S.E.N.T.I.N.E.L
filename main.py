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

from core.kernel.kernel import Kernel
from domain.entities.event import Event
from modules.demo_echo.src.demo_echo import DemoEchoModule
from modules.security_manager.src.security_manager import SecurityManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ROOT = Path(__file__).parent
GRANTED_SCOPES = ROOT / "core" / "config" / "granted_scopes.json"
AUDIT_LOG = ROOT / "core" / "config" / "audit.log"


async def main() -> None:
    security = SecurityManager(
        granted_scopes_path=GRANTED_SCOPES,
        audit_log_path=AUDIT_LOG,
    )
    kernel = Kernel(security=security)
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

    print(f"\naudit log written to: {AUDIT_LOG}")
    print(f"replies received: {len(replies)}")


if __name__ == "__main__":
    asyncio.run(main())
