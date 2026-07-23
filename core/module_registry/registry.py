"""
ModuleRegistry

Discovers modules, validates their manifest (including required_scopes)
against the SecurityManager BEFORE instantiation, wires them to the
Event Bus, and tracks their lifecycle (SAD Part 4.2-4.5).

v0.1 scope: single-version loading only. Side-by-side versioning and
hot-reload for non-critical modules (Part 4.4-4.5) are v0.2+ concerns
layered on top of this once there's more than one real module to swap.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from domain.entities.module_manifest import ModuleManifest
from domain.ports.module_port import KernelContext, Module
from domain.ports.system_ports import SecurityPort

logger = logging.getLogger("sentinel.module_registry")


class ManifestValidationError(Exception):
    pass


class ModuleRegistry:
    def __init__(self, security: SecurityPort, context: KernelContext) -> None:
        self._security = security
        self._context = context
        self._loaded: dict[str, Module] = {}
        self._manifests: dict[str, ModuleManifest] = {}

    def load_manifest(self, manifest_path: Path) -> ModuleManifest:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ModuleManifest.from_dict(data)
        self._validate_dependencies(manifest)
        self._manifests[manifest.id] = manifest
        # Register declared scopes with Security BEFORE the module can
        # ever call authorize() for itself -- closes the loophole of a
        # module requesting an undeclared scope at runtime (Part 4.2, 6.2).
        self._security.register_module_scopes(manifest.id, manifest.required_scopes)
        return manifest

    async def load(self, module: Module) -> None:
        manifest = module.manifest
        if manifest.id not in self._manifests:
            raise ManifestValidationError(
                f"module '{manifest.id}' has no registered manifest -- "
                "call load_manifest() first"
            )
        if manifest.id in self._loaded:
            logger.warning("module %s already loaded, skipping", manifest.id)
            return

        await module.on_load(self._context)
        self._loaded[manifest.id] = module
        logger.info("module loaded: %s@%s", manifest.id, manifest.version)

    async def unload(self, module_id: str) -> None:
        module = self._loaded.pop(module_id, None)
        if module is None:
            return
        await module.on_unload()
        logger.info("module unloaded: %s", module_id)

    def get(self, module_id: str) -> Module | None:
        return self._loaded.get(module_id)

    def all_manifests(self) -> dict[str, ModuleManifest]:
        return dict(self._manifests)

    def _validate_dependencies(self, manifest: ModuleManifest) -> None:
        # Core Engine and Security Manager are implicit and always
        # available; anything else must already be a registered manifest
        # (SAD Part 4.3 -- no circular / unresolved dependencies).
        implicit = {"core", "security_manager"}
        for dep in manifest.dependencies:
            if dep in implicit:
                continue
            if dep not in self._manifests:
                raise ManifestValidationError(
                    f"module '{manifest.id}' depends on unregistered "
                    f"module '{dep}'"
                )
