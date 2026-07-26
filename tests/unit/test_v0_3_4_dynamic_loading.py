"""Unit tests for v0.3.4: Dynamic Plugin Loading."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.plugin_loader.exceptions import (
    InvalidPluginStateError,
    PluginNotRunningError,
    PluginReloadError,
    PluginUnloadDeniedError,
)
from core.plugin_loader.plugin_loader import PluginLoader


def _write_plugin(folder: Path, name: str, deps: list[str] | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({
        "name": name, "version": "1.0.0", "entry_point": "plugin:Plugin",
        "dependencies": deps or [],
    }))
    (folder / "plugin.py").write_text(
        "class Plugin:\n"
        "    def on_load(self): pass\n"
        "    def on_initialize(self): pass\n"
        "    def on_start(self): pass\n"
        "    def on_stop(self): pass\n"
        "    def on_unload(self): pass\n"
    )


class RecordingBus:
    def __init__(self) -> None:
        self.published: list[str] = []

    async def publish(self, event) -> None:
        self.published.append(event.type)


def test_load_plugin_runs_full_lifecycle_and_updates_registry(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    loader = PluginLoader(tmp_path)

    instance = loader.load_plugin("weather")

    assert loader.is_loaded("weather")
    assert "weather" in loader.list_loaded_plugins()
    assert loader._lifecycle.get_state("weather").value == "running"
    assert instance is not None


def test_duplicate_load_raises_invalid_plugin_state_error(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    loader = PluginLoader(tmp_path)
    loader.load_plugin("weather")

    with pytest.raises(InvalidPluginStateError):
        loader.load_plugin("weather")


def test_unload_plugin_runs_stop_then_unload_and_updates_registry(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    loader = PluginLoader(tmp_path)
    loader.load_plugin("weather")

    loader.unload_plugin("weather")

    assert not loader.is_loaded("weather")
    assert loader._lifecycle.get_state("weather").value == "unloaded"


def test_unload_plugin_not_loaded_raises_plugin_not_running_error(tmp_path: Path):
    loader = PluginLoader(tmp_path)
    with pytest.raises(PluginNotRunningError):
        loader.unload_plugin("nonexistent")


def test_unload_denied_when_another_loaded_plugin_depends_on_it(tmp_path: Path):
    _write_plugin(tmp_path / "security_manager", "security_manager")
    _write_plugin(tmp_path / "weather", "weather", deps=["security_manager"])
    loader = PluginLoader(tmp_path)
    loader.load_plugin("security_manager")
    loader.load_plugin("weather")

    with pytest.raises(PluginUnloadDeniedError, match="weather"):
        loader.unload_plugin("security_manager")


def test_unload_allowed_after_dependent_unloaded(tmp_path: Path):
    _write_plugin(tmp_path / "security_manager", "security_manager")
    _write_plugin(tmp_path / "weather", "weather", deps=["security_manager"])
    loader = PluginLoader(tmp_path)
    loader.load_plugin("security_manager")
    loader.load_plugin("weather")

    loader.unload_plugin("weather")
    loader.unload_plugin("security_manager")

    assert not loader.is_loaded("security_manager")


def test_reload_plugin_unloads_and_loads_fresh(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    loader = PluginLoader(tmp_path)
    loader.load_plugin("weather")

    instance = loader.reload_plugin("weather")

    assert loader.is_loaded("weather")
    assert loader._lifecycle.get_state("weather").value == "running"
    assert instance is not None


def test_reload_plugin_not_loaded_raises_plugin_not_running_error(tmp_path: Path):
    loader = PluginLoader(tmp_path)
    with pytest.raises(PluginNotRunningError):
        loader.reload_plugin("nonexistent")


def test_reload_plugin_wraps_failure_in_plugin_reload_error(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    loader = PluginLoader(tmp_path)
    loader.load_plugin("weather")
    (tmp_path / "weather" / "plugin.py").unlink()

    with pytest.raises(PluginReloadError):
        loader.reload_plugin("weather")


def test_events_published_on_load_unload_reload(tmp_path: Path):
    import asyncio

    _write_plugin(tmp_path / "weather", "weather")
    bus = RecordingBus()
    loader = PluginLoader(tmp_path, event_bus=bus)

    async def run():
        loader.load_plugin("weather")
        await asyncio.sleep(0)
        loader.reload_plugin("weather")
        await asyncio.sleep(0)
        loader.unload_plugin("weather")
        await asyncio.sleep(0)

    asyncio.run(run())

    assert "PluginLoaded" in bus.published
    assert "PluginReloaded" in bus.published
    assert "PluginUnloaded" in bus.published


def test_no_event_bus_does_not_raise(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    loader = PluginLoader(tmp_path)
    loader.load_plugin("weather")
    loader.unload_plugin("weather")


def test_registry_reflects_multiple_loaded_plugins(tmp_path: Path):
    _write_plugin(tmp_path / "weather", "weather")
    _write_plugin(tmp_path / "calculator", "calculator")
    loader = PluginLoader(tmp_path)

    loader.load_plugin("weather")
    loader.load_plugin("calculator")

    assert set(loader.list_loaded_plugins().keys()) == {"weather", "calculator"}
