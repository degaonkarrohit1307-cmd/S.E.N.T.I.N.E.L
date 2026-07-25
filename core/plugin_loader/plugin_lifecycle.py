"""
PluginLifecycleManager -- v0.3.2: enforces the plugin lifecycle state
machine and invokes each plugin's optional lifecycle hooks.

State machine (the only valid successful path):

    DISCOVERED -> LOADED -> INITIALIZED -> RUNNING -> STOPPED -> UNLOADED

FAILED is reachable from any non-terminal state if a lifecycle hook
raises during a transition. FAILED and UNLOADED are both terminal in
this phase.

This class is deliberately independent of dynamic plugin import
(a later phase's responsibility -- see docs/adr/0005). It operates on
whatever "instance" object it is given at registration time; that
object is optional and may implement any subset of the five lifecycle
hooks (on_load, on_initialize, on_start, on_stop, on_unload). Missing
hooks are skipped gracefully, per the v0.3.2 Plugin API requirement.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.plugin_loader.exceptions import (
    InvalidPluginStateError,
    PluginAlreadyRunningError,
    PluginNotLoadedError,
)
from core.plugin_loader.plugin_manifest import PluginManifest
from domain.entities.plugin_state import PluginState

logger = logging.getLogger("sentinel.plugin_lifecycle")

# The state a plugin must currently be in for each action to succeed.
_REQUIRED_STATE: dict[str, PluginState] = {
    "load": PluginState.DISCOVERED,
    "initialize": PluginState.LOADED,
    "start": PluginState.INITIALIZED,
    "stop": PluginState.RUNNING,
    "unload": PluginState.STOPPED,
}

# The state a plugin moves to once an action succeeds.
_TARGET_STATE: dict[str, PluginState] = {
    "load": PluginState.LOADED,
    "initialize": PluginState.INITIALIZED,
    "start": PluginState.RUNNING,
    "stop": PluginState.STOPPED,
    "unload": PluginState.UNLOADED,
}

# The optional hook method invoked on the plugin instance for each action.
_HOOK_NAME: dict[str, str] = {
    "load": "on_load",
    "initialize": "on_initialize",
    "start": "on_start",
    "stop": "on_stop",
    "unload": "on_unload",
}

_TERMINAL_STATES: frozenset[PluginState] = frozenset(
    {PluginState.FAILED, PluginState.UNLOADED}
)


class PluginLifecycleManager:
    """
    Tracks the lifecycle state of every registered plugin and enforces
    legal transitions between states, invoking each plugin's optional
    lifecycle hooks as it goes.

    Single Responsibility: this class owns *state transition logic and
    hook invocation only*. It does not discover plugins (PluginLoader's
    job) and does not dynamically import plugin code (a future phase's
    job) -- callers register an already-obtained manifest and an
    optional instance object.
    """

    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        self._instances: dict[str, Optional[Any]] = {}
        self._states: dict[str, PluginState] = {}

    # -- registration -----------------------------------------------------

    def register_plugin(
        self, manifest: PluginManifest, instance: Optional[Any] = None
    ) -> None:
        """
        Register a discovered plugin with the lifecycle manager,
        starting in the DISCOVERED state.

        `instance` is optional and may be None (e.g. during discovery-
        only testing, or before dynamic import has produced a real
        object). If provided, it may implement any subset of
        on_load/on_initialize/on_start/on_stop/on_unload -- missing
        hooks are simply skipped when their corresponding transition
        runs.

        Re-registering an already-known plugin name resets it back to
        DISCOVERED with the new manifest/instance; this is intentional,
        to support re-registration in tests and future reload flows,
        and is logged at INFO level so it is never silent.
        """
        if manifest.name in self._states:
            logger.info(
                "re-registering plugin '%s' (was in state %s); resetting to DISCOVERED",
                manifest.name,
                self._states[manifest.name].value,
            )
        self._manifests[manifest.name] = manifest
        self._instances[manifest.name] = instance
        self._states[manifest.name] = PluginState.DISCOVERED
        logger.debug("plugin '%s' registered in state DISCOVERED", manifest.name)

    # -- lifecycle transitions ---------------------------------------------

    def load_plugin(self, name: str) -> None:
        """Transition DISCOVERED -> LOADED, calling on_load() if present."""
        self._transition(name, "load")

    def initialize_plugin(self, name: str) -> None:
        """Transition LOADED -> INITIALIZED, calling on_initialize() if present."""
        self._transition(name, "initialize")

    def start_plugin(self, name: str) -> None:
        """Transition INITIALIZED -> RUNNING, calling on_start() if present."""
        self._transition(name, "start")

    def stop_plugin(self, name: str) -> None:
        """Transition RUNNING -> STOPPED, calling on_stop() if present."""
        self._transition(name, "stop")

    def unload_plugin(self, name: str) -> None:
        """Transition STOPPED -> UNLOADED, calling on_unload() if present."""
        self._transition(name, "unload")

    # -- introspection ----------------------------------------------------

    def get_state(self, name: str) -> PluginState:
        """Return the current lifecycle state of a registered plugin.

        Raises PluginNotLoadedError if `name` was never registered."""
        if name not in self._states:
            raise PluginNotLoadedError(
                f"plugin '{name}' is not registered with the lifecycle manager"
            )
        return self._states[name]

    def list_plugins(self) -> dict[str, PluginState]:
        """Return a snapshot mapping of every registered plugin name to
        its current lifecycle state."""
        return dict(self._states)

    # -- internals ------------------------------------------------------------

    def _transition(self, name: str, action: str) -> None:
        if name not in self._states:
            raise PluginNotLoadedError(
                f"plugin '{name}' is not registered with the lifecycle manager"
            )

        current = self._states[name]
        required = _REQUIRED_STATE[action]
        target = _TARGET_STATE[action]

        if current == PluginState.DISCOVERED and action != "load":
            raise PluginNotLoadedError(
                f"plugin '{name}' has not been loaded yet; cannot perform "
                f"'{action}' from state {current.value}"
            )

        if current == target:
            if target == PluginState.RUNNING:
                raise PluginAlreadyRunningError(
                    f"plugin '{name}' is already running"
                )
            raise InvalidPluginStateError(
                f"plugin '{name}' is already in state {current.value}; "
                f"cannot repeat the '{action}' transition"
            )

        if current != required:
            reason = "terminal state" if current in _TERMINAL_STATES else "wrong state"
            raise InvalidPluginStateError(
                f"invalid transition for plugin '{name}': cannot perform "
                f"'{action}' from {reason} {current.value} "
                f"(requires {required.value})"
            )

        self._invoke_hook_and_advance(name, action, target)

    def _invoke_hook_and_advance(
        self, name: str, action: str, target: PluginState
    ) -> None:
        current = self._states[name]
        hook_name = _HOOK_NAME[action]
        instance = self._instances.get(name)

        try:
            if instance is not None:
                hook = getattr(instance, hook_name, None)
                if callable(hook):
                    hook()
                else:
                    logger.debug(
                        "plugin '%s' does not implement '%s'; continuing gracefully",
                        name,
                        hook_name,
                    )
            else:
                logger.debug(
                    "plugin '%s' has no associated instance; skipping '%s' hook",
                    name,
                    hook_name,
                )
        except Exception:
            self._states[name] = PluginState.FAILED
            logger.exception(
                "plugin '%s' hook '%s' raised during '%s' transition; "
                "marking plugin as FAILED",
                name,
                hook_name,
                action,
            )
            raise

        self._states[name] = target
        logger.info(
            "plugin '%s' transitioned %s -> %s", name, current.value, target.value
        )
