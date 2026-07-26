"""
PluginDependency -- a directed edge in the plugin dependency graph:
"plugin_name" depends on "depends_on".

Framework-free value object, consistent with the rest of
domain/entities/* (e.g. Event, ModuleManifest): plain data, no
behavior. Validating whether an edge is *legal* (self-dependency,
unknown target, participation in a cycle) is DependencyResolver's
responsibility in core/plugin_loader/, not this entity's -- domain
entities here describe shape, not business rules that require raising
application-layer errors.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginDependency:
    """A single directed dependency edge: `plugin_name` depends on
    `depends_on`. Two PluginDependency instances are equal if both
    fields match (standard frozen-dataclass equality), which makes them
    convenient to collect in sets when building or inspecting a graph."""

    plugin_name: str
    depends_on: str
