"""
PluginManifest -- strongly-typed representation of a plugin's
manifest.json.

Deliberately separate from domain/entities/module_manifest.py's
ModuleManifest: that class describes module.manifest.json for the
existing Module Registry (v0.1), a different system with a different
schema (required_scopes vs permissions, no entry_point field since
Module Registry modules are constructed directly by whoever wires them,
not dynamically imported). SemVer IS reused from that file rather than
redefined here -- it's a generic value object with no coupling to
either manifest schema.

Phase 1 scope: parsing only. No lifecycle interface (Plugin base class),
no dependency-graph validation, no permission whitelist checking -- all
deferred to their own phases.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from domain.entities.module_manifest import SemVer
from core.plugin_loader.exceptions import PluginManifestError

_REQUIRED_FIELDS: tuple[str, ...] = ("name", "version", "entry_point")


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: SemVer
    entry_point: str
    author: str = ""
    description: str = ""
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    source_dir: Optional[Path] = None  # the folder this manifest was read from

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_dir: Optional[Path] = None) -> "PluginManifest":
        """Parse a raw dict (already loaded from JSON) into a
        PluginManifest. Raises PluginManifestError if a required field
        is missing or the version string doesn't parse -- callers
        (PluginLoader) are expected to catch this and skip the
        offending directory rather than let it propagate."""
        missing = [f for f in _REQUIRED_FIELDS if not data.get(f)]
        if missing:
            raise PluginManifestError(
                f"manifest missing required field(s): {', '.join(missing)}"
            )

        try:
            version = SemVer.parse(str(data["version"]))
        except (ValueError, TypeError) as exc:
            raise PluginManifestError(
                f"invalid version '{data.get('version')}' for plugin "
                f"'{data.get('name')}': {exc}"
            ) from exc

        entry_point = data["entry_point"]
        if not isinstance(entry_point, str) or not entry_point.strip():
            raise PluginManifestError(
                f"plugin '{data.get('name')}' has an invalid entry_point: {entry_point!r}"
            )

        dependencies = data.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise PluginManifestError(
                f"plugin '{data.get('name')}' field 'dependencies' must be a list"
            )

        permissions = data.get("permissions", [])
        if not isinstance(permissions, list):
            raise PluginManifestError(
                f"plugin '{data.get('name')}' field 'permissions' must be a list"
            )

        return cls(
            name=data["name"],
            version=version,
            entry_point=entry_point,
            author=str(data.get("author", "")),
            description=str(data.get("description", "")),
            dependencies=tuple(dependencies),
            permissions=tuple(permissions),
            enabled=bool(data.get("enabled", True)),
            source_dir=source_dir,
        )

    @classmethod
    def from_file(cls, manifest_path: Path) -> "PluginManifest":
        """Read and parse a manifest.json file. Raises
        PluginManifestError on invalid JSON or invalid content -- never
        raises a raw json.JSONDecodeError, so callers only need to
        catch one exception type."""
        try:
            raw_text = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PluginManifestError(f"could not read manifest file {manifest_path}: {exc}") from exc

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"invalid JSON in manifest {manifest_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise PluginManifestError(
                f"manifest {manifest_path} must contain a JSON object at the top level"
            )

        return cls.from_dict(raw, source_dir=manifest_path.parent)
