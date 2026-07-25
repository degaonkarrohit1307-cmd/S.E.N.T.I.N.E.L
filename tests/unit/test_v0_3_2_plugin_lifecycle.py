"""
Unit tests for v0.3.2: Plugin Lifecycle Management.
Run with:  pytest tests/unit/test_v0_3_2_plugin_lifecycle.py -v
"""
from __future__ import annotations

import pytest

from core.plugin_loader.exceptions import (
    InvalidPluginStateError,
    PluginAlreadyRunningError,
    PluginNotLoadedError,
)
from core.plugin_loader.plugin_lifecycle import PluginLifecycleManager
from core.plugin_loader.plugin_manifest import PluginManifest
from domain.entities.plugin_state import PluginState


def _make_manifest(name: str = "weather") -> PluginManifest:
    return PluginManifest.from_dict({
        "name": name,
        "version": "1.0.0",
        "entry_point": "plugin:WeatherPlugin",
        "permissions": ["network.http"],
    })


class RecordingPlugin:
    """A plugin instance implementing all five hooks, recording call order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_load(self) -> None:
        self.calls.append("on_load")

    def on_initialize(self) -> None:
        self.calls.append("on_initialize")

    def on_start(self) -> None:
        self.calls.append("on_start")

    def on_stop(self) -> None:
        self.calls.append("on_stop")

    def on_unload(self) -> None:
        self.calls.append("on_unload")


class PartialHookPlugin:
    """A plugin instance implementing only SOME hooks -- the rest must
    be skipped gracefully rather than raising AttributeError."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_load(self) -> None:
        self.calls.append("on_load")

    # deliberately no on_initialize, on_start, on_stop, on_unload


class FailingOnStartPlugin:
    def on_load(self) -> None:
        pass

    def on_initialize(self) -> None:
        pass

    def on_start(self) -> None:
        raise ValueError("boom: simulated startup failure")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_plugin_starts_in_discovered_state():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    assert manager.get_state("weather") == PluginState.DISCOVERED


def test_get_state_unknown_plugin_raises_plugin_not_loaded_error():
    manager = PluginLifecycleManager()
    with pytest.raises(PluginNotLoadedError, match="not registered"):
        manager.get_state("nonexistent")


def test_transition_on_never_registered_plugin_raises_plugin_not_loaded_error():
    """Calling a lifecycle method directly on a name that was never
    registered at all (distinct from a registered-but-still-DISCOVERED
    plugin) must also raise PluginNotLoadedError."""
    manager = PluginLifecycleManager()
    with pytest.raises(PluginNotLoadedError, match="not registered"):
        manager.load_plugin("never_registered")


def test_re_registering_resets_state_to_discovered():
    manager = PluginLifecycleManager()
    manifest = _make_manifest()
    manager.register_plugin(manifest)
    manager.load_plugin("weather")
    assert manager.get_state("weather") == PluginState.LOADED

    manager.register_plugin(manifest)  # re-register
    assert manager.get_state("weather") == PluginState.DISCOVERED


def test_list_plugins_returns_snapshot_of_all_registered_states():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest("weather"))
    manager.register_plugin(_make_manifest("calculator"))
    manager.load_plugin("weather")

    snapshot = manager.list_plugins()
    assert snapshot == {
        "weather": PluginState.LOADED,
        "calculator": PluginState.DISCOVERED,
    }


# ---------------------------------------------------------------------------
# Valid lifecycle -- full chain
# ---------------------------------------------------------------------------

def test_full_valid_lifecycle_transitions_correctly():
    manager = PluginLifecycleManager()
    plugin = RecordingPlugin()
    manager.register_plugin(_make_manifest(), instance=plugin)

    assert manager.get_state("weather") == PluginState.DISCOVERED

    manager.load_plugin("weather")
    assert manager.get_state("weather") == PluginState.LOADED

    manager.initialize_plugin("weather")
    assert manager.get_state("weather") == PluginState.INITIALIZED

    manager.start_plugin("weather")
    assert manager.get_state("weather") == PluginState.RUNNING

    manager.stop_plugin("weather")
    assert manager.get_state("weather") == PluginState.STOPPED

    manager.unload_plugin("weather")
    assert manager.get_state("weather") == PluginState.UNLOADED

    assert plugin.calls == ["on_load", "on_initialize", "on_start", "on_stop", "on_unload"]


def test_lifecycle_works_with_no_instance_at_all():
    """instance=None must be handled gracefully throughout the entire
    chain -- no hook calls are attempted, but no error is raised."""
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())  # no instance

    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    manager.start_plugin("weather")
    manager.stop_plugin("weather")
    manager.unload_plugin("weather")

    assert manager.get_state("weather") == PluginState.UNLOADED


def test_missing_hooks_are_skipped_gracefully():
    """A plugin implementing only on_load must not raise AttributeError
    when on_initialize/on_start/on_stop/on_unload are invoked."""
    manager = PluginLifecycleManager()
    plugin = PartialHookPlugin()
    manager.register_plugin(_make_manifest(), instance=plugin)

    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    manager.start_plugin("weather")
    manager.stop_plugin("weather")
    manager.unload_plugin("weather")

    assert manager.get_state("weather") == PluginState.UNLOADED
    assert plugin.calls == ["on_load"]


# ---------------------------------------------------------------------------
# Invalid lifecycle transitions
# ---------------------------------------------------------------------------

def test_discovered_to_running_raises_invalid_state_error():
    """Skipping straight from DISCOVERED to RUNNING (never loaded or
    initialized) must be rejected -- this is the 'never loaded' case,
    so PluginNotLoadedError (a subclass of InvalidPluginStateError)."""
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())

    with pytest.raises(InvalidPluginStateError):
        manager.start_plugin("weather")


def test_discovered_to_running_raises_plugin_not_loaded_error_specifically():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())

    with pytest.raises(PluginNotLoadedError):
        manager.start_plugin("weather")


def test_loaded_to_running_skipping_initialize_raises():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")

    with pytest.raises(InvalidPluginStateError, match="requires initialized"):
        manager.start_plugin("weather")


def test_load_plugin_twice_raises_invalid_state_error():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")

    with pytest.raises(InvalidPluginStateError, match="already in state loaded"):
        manager.load_plugin("weather")


def test_unload_before_load_raises_plugin_not_loaded_error():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())

    with pytest.raises(PluginNotLoadedError):
        manager.unload_plugin("weather")


def test_initialize_before_load_raises_plugin_not_loaded_error():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())

    with pytest.raises(PluginNotLoadedError):
        manager.initialize_plugin("weather")


def test_stop_before_start_raises_plugin_not_loaded_error():
    """stop_plugin called while still DISCOVERED (never loaded at all)."""
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())

    with pytest.raises(PluginNotLoadedError):
        manager.stop_plugin("weather")


def test_stop_from_loaded_state_raises_invalid_state_error():
    """stop_plugin called after loading but before starting -- this IS
    'loaded', so it's a wrong-point-in-chain error, not 'not loaded'."""
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")

    with pytest.raises(InvalidPluginStateError, match="requires running"):
        manager.stop_plugin("weather")


# ---------------------------------------------------------------------------
# Duplicate start / stop twice
# ---------------------------------------------------------------------------

def test_duplicate_start_raises_plugin_already_running_error():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    manager.start_plugin("weather")

    with pytest.raises(PluginAlreadyRunningError, match="already running"):
        manager.start_plugin("weather")

    # state must remain RUNNING, not corrupted by the failed attempt
    assert manager.get_state("weather") == PluginState.RUNNING


def test_stop_twice_raises_invalid_state_error():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    manager.start_plugin("weather")
    manager.stop_plugin("weather")

    with pytest.raises(InvalidPluginStateError, match="already in state stopped"):
        manager.stop_plugin("weather")

    assert manager.get_state("weather") == PluginState.STOPPED


def test_unload_twice_raises_invalid_state_error():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    manager.start_plugin("weather")
    manager.stop_plugin("weather")
    manager.unload_plugin("weather")

    with pytest.raises(InvalidPluginStateError):
        manager.unload_plugin("weather")


def test_operations_on_terminal_unloaded_state_all_raise():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    manager.start_plugin("weather")
    manager.stop_plugin("weather")
    manager.unload_plugin("weather")

    with pytest.raises(InvalidPluginStateError):
        manager.load_plugin("weather")
    with pytest.raises(InvalidPluginStateError):
        manager.start_plugin("weather")


# ---------------------------------------------------------------------------
# Exception propagation from lifecycle hooks
# ---------------------------------------------------------------------------

def test_hook_exception_propagates_to_caller():
    manager = PluginLifecycleManager()
    plugin = FailingOnStartPlugin()
    manager.register_plugin(_make_manifest(), instance=plugin)
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")

    with pytest.raises(ValueError, match="boom: simulated startup failure"):
        manager.start_plugin("weather")


def test_hook_exception_marks_plugin_as_failed():
    manager = PluginLifecycleManager()
    plugin = FailingOnStartPlugin()
    manager.register_plugin(_make_manifest(), instance=plugin)
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")

    with pytest.raises(ValueError):
        manager.start_plugin("weather")

    assert manager.get_state("weather") == PluginState.FAILED


def test_operations_after_failure_raise_invalid_state_error():
    manager = PluginLifecycleManager()
    plugin = FailingOnStartPlugin()
    manager.register_plugin(_make_manifest(), instance=plugin)
    manager.load_plugin("weather")
    manager.initialize_plugin("weather")
    with pytest.raises(ValueError):
        manager.start_plugin("weather")

    with pytest.raises(InvalidPluginStateError):
        manager.stop_plugin("weather")
    with pytest.raises(InvalidPluginStateError):
        manager.unload_plugin("weather")


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_state_persists_across_multiple_get_state_calls():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest())
    manager.load_plugin("weather")

    assert manager.get_state("weather") == PluginState.LOADED
    assert manager.get_state("weather") == PluginState.LOADED
    assert manager.get_state("weather") == PluginState.LOADED


def test_state_is_independent_per_plugin():
    manager = PluginLifecycleManager()
    manager.register_plugin(_make_manifest("weather"))
    manager.register_plugin(_make_manifest("calculator"))

    manager.load_plugin("weather")
    manager.initialize_plugin("weather")

    assert manager.get_state("weather") == PluginState.INITIALIZED
    assert manager.get_state("calculator") == PluginState.DISCOVERED
