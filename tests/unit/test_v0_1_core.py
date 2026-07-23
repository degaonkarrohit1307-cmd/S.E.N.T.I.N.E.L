"""
Unit + contract tests for the v0.1 slice: Event Bus, Module Registry,
Security Manager. Run with:  pytest tests/unit/test_v0_1_core.py -v
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.event_bus.event_bus import AsyncEventBus
from core.kernel.kernel import Kernel
from domain.entities.event import Event, Priority
from modules.security_manager.src.security_manager import SecurityManager


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_bus_delivers_to_subscriber():
    bus = AsyncEventBus()
    await bus.start()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("test.event", handler)
    await bus.publish(Event(type="test.event", source="test", payload={"x": 1}))
    await asyncio.sleep(0.1)
    await bus.stop()

    assert len(received) == 1
    assert received[0].payload == {"x": 1}


@pytest.mark.asyncio
async def test_event_bus_circuit_breaker_disables_failing_handler():
    bus = AsyncEventBus()
    await bus.start()
    call_count = 0

    async def failing_handler(event: Event) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    bus.subscribe("test.fail", failing_handler)
    for _ in range(5):
        await bus.publish(Event(type="test.fail", source="test"))
    await asyncio.sleep(0.2)
    await bus.stop()

    # breaker trips after 3 consecutive failures -- handler should not be
    # invoked a 4th or 5th time
    assert call_count == 3


@pytest.mark.asyncio
async def test_critical_priority_has_its_own_lane():
    bus = AsyncEventBus()
    await bus.start()
    order: list[str] = []

    async def handler(event: Event) -> None:
        order.append(event.type)

    bus.subscribe("normal.evt", handler)
    bus.subscribe("critical.evt", handler)

    # flood normal lane first
    for _ in range(20):
        await bus.publish(Event(type="normal.evt", source="test", priority=Priority.NORMAL))
    await bus.publish(Event(type="critical.evt", source="test", priority=Priority.CRITICAL))

    await asyncio.sleep(0.3)
    await bus.stop()

    # critical event must not be starved indefinitely behind the flood
    assert "critical.evt" in order


# ---------------------------------------------------------------------------
# Security Manager
# ---------------------------------------------------------------------------

def test_security_denies_undeclared_scope(tmp_path: Path):
    granted = tmp_path / "granted.json"
    granted.write_text(json.dumps({"mod_a": ["scope.a"]}))
    audit = tmp_path / "audit.log"

    sec = SecurityManager(granted_scopes_path=granted, audit_log_path=audit)
    # mod_a never DECLARED scope.b in its manifest, even though it's not
    # in the granted file either -- authorize must fail closed
    assert sec.authorize("mod_a", "scope.b") is False


def test_security_denies_declared_but_ungranted_scope(tmp_path: Path):
    granted = tmp_path / "granted.json"
    granted.write_text(json.dumps({}))  # nothing granted
    audit = tmp_path / "audit.log"

    sec = SecurityManager(granted_scopes_path=granted, audit_log_path=audit)
    sec.register_module_scopes("mod_a", ("scope.a",))
    assert sec.authorize("mod_a", "scope.a") is False


def test_security_grants_declared_and_granted_scope(tmp_path: Path):
    granted = tmp_path / "granted.json"
    granted.write_text(json.dumps({"mod_a": ["scope.a"]}))
    audit = tmp_path / "audit.log"

    sec = SecurityManager(granted_scopes_path=granted, audit_log_path=audit)
    sec.register_module_scopes("mod_a", ("scope.a",))
    assert sec.authorize("mod_a", "scope.a") is True

    # every decision must be audited (SAD Part 6.6)
    lines = audit.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["granted"] is True


# ---------------------------------------------------------------------------
# Kernel boot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kernel_boots_and_stops_cleanly(tmp_path: Path):
    granted = tmp_path / "granted.json"
    granted.write_text(json.dumps({}))
    audit = tmp_path / "audit.log"
    sec = SecurityManager(granted_scopes_path=granted, audit_log_path=audit)

    kernel = Kernel(security=sec)
    await kernel.start()
    await kernel.stop()
    # no exception = success; this is the minimal "does the kernel boot" test
