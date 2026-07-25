"""
PluginLoader -- Phase 1: discovery only.

Responsibilities in this phase:
    - recursively scan a root directory for manifest.json files
    - parse each one into a PluginManifest
    - skip anything invalid (bad JSON, missing required fields, or no
      manifest.json present at all) gracefully, with a logged reason,
      rather than aborting the whole scan
    - return the list of successfully discovered plugins

Explicitly NOT in this phase (later phases):
    - dependency resolution / cycle detection
    - permission whitelist validation
    - duplicate-name detection
    - dynamic import of plugin code
    - lifecycle (initialize/start/stop/shutdown)
    - enable/disable/reload

Coexistence with the existing Module Registry (v0.1): that system's
modules (e.g. modules/security_manager/, modules/demo_echo/) use
module.manifest.json, a different filename. This loader only ever looks
for manifest.json, so the two systems never collide even though they
currently share the same modules/ directory.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.plugin_loader.exceptions import PluginManifestError
from core.plugin_loader.plugin_manifest import PluginManifest

logger = logging.getLogger("sentinel.plugin_loader")

MANIFEST_FILENAME = "manifest.json"


class PluginLoader:
    """
    Stateless discovery. Holds no record of "loaded" or "enabled"
    plugins -- that lifecycle bookkeeping belongs to a future
    PluginManager (Single Responsibility: discovering/parsing manifests
    is a distinct concern from tracking runtime state).
    """

    def __init__(self, plugin_root: Path) -> None:
        """`plugin_root` is injected rather than hardcoded, so callers
        (main.py today, PluginManager + ConfigurationManager in a later
        phase) decide where plugins live -- this class doesn't know or
        care that the default happens to be "modules/"."""
        self._plugin_root = plugin_root

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
