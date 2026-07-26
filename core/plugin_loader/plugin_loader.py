"""
PluginLoader -- discovery, plus (as of v0.3.3) dependency-ordered
discovery.

Responsibilities:
    - recursively scan a root directory for manifest.json files
    - parse each one into a PluginManifest
    - skip anything invalid (bad JSON, missing required fields, or no
      manifest.json present at all) gracefully, with a logged reason,
      rather than aborting the whole scan
    - return the list of successfully discovered plugins, either in raw
      path-sorted order (discover()) or in a safe dependency-resolved
      load order (discover_in_dependency_order(), v0.3.3)

Explicitly NOT in this class's responsibility (later phases):
    - dynamic import of plugin code
    - lifecycle (initialize/start/stop/shutdown) -- see
      core/plugin_loader/plugin_lifecycle.py
    - enable/disable/reload

Coexistence with the existing Module Registry (v0.1): that system's
modules (e.g. modules/security_manager/, modules/demo_echo/) use
module.manifest.json, a different filename. This loader only ever looks
for manifest.json, so the two systems never collide even though they
currently share the same modules/ directory.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from core.plugin_loader.dependency_graph import DependencyGraph
from core.plugin_loader.dependency_resolver import DependencyResolver
from core.plugin_loader.exceptions import (
    InvalidPluginStateError,
    PluginManifestError,
    PluginNotRunningError,
    PluginReloadError,
    PluginUnloadDeniedError,
)
from core.plugin_loader.plugin_lifecycle import PluginLifecycleManager
from core.plugin_loader.plugin_manifest import PluginManifest
from domain.entities.event import Event

logger = logging.getLogger("sentinel.plugin_loader")

MANIFEST_FILENAME = "manifest.json"


class PluginLoader:
    """
    Discovery, dependency-ordered discovery, plus (v0.3.4) runtime
    load/unload/reload of plugin code, using PluginLifecycleManager for
    state transitions and DependencyGraph to guard unloads against
    still-depended-upon plugins.
    """

    def __init__(
        self,
        plugin_root: Path,
        lifecycle_manager: Optional[PluginLifecycleManager] = None,
        dependency_graph: Optional[DependencyGraph] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        """`plugin_root` is injected rather than hardcoded. `lifecycle_manager`
        and `dependency_graph` are optional (Dependency Injection) so
        tests can supply their own; `event_bus` is optional and, if
        given, must expose an async `publish(event)` -- PluginLoaded/
        PluginUnloaded/PluginReloaded events are published through it,
        fire-and-forget, exactly as ConfigurationManager does for
        config.changed (no running loop = silently skipped)."""
        self._plugin_root = plugin_root
        self._lifecycle = lifecycle_manager or PluginLifecycleManager()
        self._graph = dependency_graph or DependencyGraph()
        self._event_bus = event_bus
        self._registry: dict[str, PluginManifest] = {}
        self._instances: dict[str, Any] = {}
        self._module_qualnames: dict[str, str] = {}

    def discover(self) -> list[PluginManifest]:
        """
        Recursively scan plugin_root for every manifest.json file,
        parse each into a PluginManifest, and return the successfully
        parsed ones in a deterministic (path-sorted) order.

        A directory that has no manifest.json anywhere under it simply
        contributes nothing -- this is the normal case, not an error.
        A manifest.json that fails to parse is logged as a warning and
        skipped; it does not stop the rest of the scan.
        """
        if not self._plugin_root.exists():
            logger.warning(
                "plugin root does not exist, skipping discovery: %s",
                self._plugin_root,
            )
            return []

        if not self._plugin_root.is_dir():
            logger.warning(
                "plugin root is not a directory, skipping discovery: %s",
                self._plugin_root,
            )
            return []

        manifest_paths = sorted(self._plugin_root.rglob(MANIFEST_FILENAME))
        logger.info(
            "scanning %s: found %d candidate manifest file(s)",
            self._plugin_root,
            len(manifest_paths),
        )

        discovered: list[PluginManifest] = []
        for manifest_path in manifest_paths:
            manifest = self._try_parse(manifest_path)
            if manifest is not None:
                discovered.append(manifest)

        logger.info(
            "discovery complete: %d valid plugin manifest(s) out of %d candidate(s)",
            len(discovered),
            len(manifest_paths),
        )
        return discovered

    def discover_in_dependency_order(self) -> list[PluginManifest]:
        """
        Discover plugins exactly as discover() does, then reorder the
        result using DependencyResolver so plugins come back in a safe
        load order (every plugin appears after all of its
        dependencies) instead of discover()'s raw path-sorted order.

        This is purely additive: discover() itself is completely
        unchanged, so every existing caller and test that depends on
        its current path-sorted, error-tolerant behavior is unaffected.

        Raises whatever DependencyResolver.resolve() raises --
        DuplicatePluginError, InvalidDependencyError,
        MissingDependencyError, or CircularDependencyError -- if the
        discovered set of manifests has an invalid dependency graph.
        Unlike discover(), which tolerates a single bad manifest by
        skipping it, an invalid *dependency graph* spans multiple
        plugins at once and cannot be silently partially resolved, so
        it is surfaced to the caller rather than swallowed.
        """
        manifests = self.discover()
        resolver = DependencyResolver()
        order = resolver.resolve(manifests)
        manifests_by_name = {manifest.name: manifest for manifest in manifests}
        return [manifests_by_name[name] for name in order]

    # -- v0.3.4: runtime load/unload/reload --------------------------------

    def load_plugin(self, name: str) -> Any:
        """
        Dynamically import and run a discovered plugin through
        load -> initialize -> start, updating the runtime registry and
        dependency graph, and publishing PluginLoaded. Raises whatever
        PluginLifecycleManager raises (e.g. InvalidPluginStateError) if
        `name` is already loaded -- this is the "duplicate load" case.
        """
        if name in self._registry:
            raise InvalidPluginStateError(f"plugin '{name}' is already loaded")

        manifest = self._find_manifest(name)
        instance_cls = self._import_entry_point(manifest)
        instance = instance_cls()

        self._lifecycle.register_plugin(manifest, instance=instance)
        self._lifecycle.load_plugin(name)
        self._lifecycle.initialize_plugin(name)
        self._lifecycle.start_plugin(name)

        self._registry[name] = manifest
        self._instances[name] = instance
        self._graph.add_plugin(name, manifest.dependencies)

        logger.info("plugin '%s' loaded, initialized, and started", name)
        self._publish("PluginLoaded", name)
        return instance

    def unload_plugin(self, name: str) -> None:
        """
        Stop and unload a running plugin, updating the runtime registry
        and dependency graph, and publishing PluginUnloaded.

        Raises PluginNotRunningError if `name` is not currently loaded.
        Raises PluginUnloadDeniedError if another currently loaded
        plugin still depends on `name`.
        """
        if name not in self._registry:
            raise PluginNotRunningError(f"plugin '{name}' is not currently loaded")

        dependents = self._graph.get_dependents(name) & self._registry.keys()
        if dependents:
            raise PluginUnloadDeniedError(
                f"cannot unload '{name}': still depended on by {sorted(dependents)}"
            )

        self._lifecycle.stop_plugin(name)
        self._lifecycle.unload_plugin(name)

        self._graph.remove_plugin(name)
        del self._registry[name]
        self._instances.pop(name, None)
        qualname = self._module_qualnames.pop(name, None)
        if qualname:
            sys.modules.pop(qualname, None)

        logger.info("plugin '%s' stopped and unloaded", name)
        self._publish("PluginUnloaded", name)

    def reload_plugin(self, name: str) -> Any:
        """
        Unload then load a plugin fresh (re-reading its manifest and
        re-importing its code from disk), publishing PluginReloaded.
        Wraps any failure in PluginReloadError.
        """
        if name not in self._registry:
            raise PluginNotRunningError(f"plugin '{name}' is not currently loaded")

        try:
            self.unload_plugin(name)
            instance = self.load_plugin(name)
        except Exception as exc:
            raise PluginReloadError(f"failed to reload plugin '{name}': {exc}") from exc

        logger.info("plugin '%s' reloaded", name)
        self._publish("PluginReloaded", name)
        return instance

    def is_loaded(self, name: str) -> bool:
        """Registry query: is `name` currently loaded/running."""
        return name in self._registry

    def list_loaded_plugins(self) -> dict[str, PluginManifest]:
        """Snapshot of the runtime registry (currently loaded plugins)."""
        return dict(self._registry)

    # -- internals: dynamic import -----------------------------------------

    def _find_manifest(self, name: str) -> PluginManifest:
        for manifest in self.discover():
            if manifest.name == name:
                return manifest
        raise PluginManifestError(f"plugin '{name}' was not found via discovery")

    def _import_entry_point(self, manifest: PluginManifest) -> type:
        module_part, _, class_name = manifest.entry_point.partition(":")
        if manifest.source_dir is None:
            raise PluginManifestError(f"plugin '{manifest.name}' has no known source directory")
        module_file = manifest.source_dir / f"{module_part}.py"
        if not module_file.exists():
            raise PluginManifestError(
                f"entry point module file not found for plugin '{manifest.name}': {module_file}"
            )

        qualname = f"sentinel_plugin_{manifest.name}_{module_part}"
        spec = importlib.util.spec_from_file_location(qualname, module_file)
        if spec is None or spec.loader is None:
            raise PluginManifestError(f"could not build import spec for {module_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[qualname] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(qualname, None)
            raise PluginManifestError(
                f"error executing plugin module for '{manifest.name}': {exc}"
            ) from exc

        if not hasattr(module, class_name):
            sys.modules.pop(qualname, None)
            raise PluginManifestError(
                f"class '{class_name}' not found in {module_file} for plugin '{manifest.name}'"
            )

        self._module_qualnames[manifest.name] = qualname
        return getattr(module, class_name)

    def _publish(self, event_type: str, name: str) -> None:
        if self._event_bus is None:
            return
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._event_bus.publish(
                    Event(type=event_type, source="plugin_loader", payload={"name": name})
                )
            )
        except RuntimeError:
            logger.debug("no running event loop; skipping %s publish", event_type)

    def _try_parse(self, manifest_path: Path) -> PluginManifest | None:
        try:
            manifest = PluginManifest.from_file(manifest_path)
        except PluginManifestError as exc:
            logger.warning(
                "skipping invalid plugin manifest at %s: %s", manifest_path, exc
            )
            return None
        except Exception:  # noqa: BLE001 -- discovery must never crash on one bad plugin
            logger.exception(
                "unexpected error parsing manifest at %s, skipping", manifest_path
            )
            return None

        logger.debug(
            "discovered plugin '%s' v%s at %s",
            manifest.name,
            manifest.version,
            manifest_path.parent,
        )
        return manifest
