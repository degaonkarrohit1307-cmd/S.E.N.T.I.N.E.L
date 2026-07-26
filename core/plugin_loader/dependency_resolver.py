"""
DependencyResolver -- validates a set of discovered plugin manifests
and computes a safe loading order via topological sort (Kahn's
Algorithm).

Responsibilities:
    - detect duplicate plugin names among the manifests given
    - detect invalid dependency declarations (self-dependency, blank names)
    - detect dependencies that reference an unknown plugin
    - detect circular dependency chains
    - return plugin names in an order where every plugin appears after
      all of its dependencies -- a valid load order

This class does not import plugins, does not know about manifests'
entry_point or permissions fields, and does not touch lifecycle state.
It operates on PluginManifest only far enough to read `.name` and
`.dependencies`, translating those into the generic (name, deps) shape
DependencyGraph expects -- keeping the graph itself fully decoupled
from the manifest schema.
"""
from __future__ import annotations

from collections import deque
from typing import Iterable, Optional

from core.plugin_loader.dependency_graph import DependencyGraph
from core.plugin_loader.exceptions import (
    CircularDependencyError,
    DuplicatePluginError,
    InvalidDependencyError,
    MissingDependencyError,
)
from core.plugin_loader.plugin_manifest import PluginManifest


class DependencyResolver:
    """
    Resolves a safe plugin loading order from a set of discovered
    manifests, raising a specific PluginDependencyError subclass for
    each distinct class of invalid dependency graph.
    """

    def __init__(self, graph: Optional[DependencyGraph] = None) -> None:
        """
        `graph` is optional and constructor-injected (Dependency
        Injection) so callers -- tests, or a future caller wanting a
        pre-populated/fake graph -- can supply their own; by default a
        fresh DependencyGraph is created and fully rebuilt on every
        call to resolve().
        """
        self._graph = graph if graph is not None else DependencyGraph()

    def resolve(self, manifests: Iterable[PluginManifest]) -> list[str]:
        """
        Validate the given manifests and return their names in a valid
        loading order (every name appears after all of its
        dependencies).

        Raises:
            DuplicatePluginError: two manifests share the same name.
            InvalidDependencyError: a manifest declares a self-dependency
                or a blank/non-string dependency entry.
            MissingDependencyError: a manifest depends on a plugin name
                not present among the given manifests.
            CircularDependencyError: the dependency graph contains a cycle.
        """
        manifest_list = list(manifests)

        self._check_duplicates(manifest_list)
        self._check_valid_dependency_entries(manifest_list)

        self._graph.build_graph((m.name, m.dependencies) for m in manifest_list)

        known_names = {m.name for m in manifest_list}
        self._check_missing_dependencies(manifest_list, known_names)

        return self._topological_sort(known_names)

    @property
    def graph(self) -> DependencyGraph:
        """Expose the underlying graph for introspection (e.g. a
        diagnostics UI listing dependents of a given plugin) after a
        successful resolve() call."""
        return self._graph

    # -- validation --------------------------------------------------------

    def _check_duplicates(self, manifests: list[PluginManifest]) -> None:
        seen: set[str] = set()
        for manifest in manifests:
            if manifest.name in seen:
                raise DuplicatePluginError(
                    f"duplicate plugin name found during dependency "
                    f"resolution: '{manifest.name}'"
                )
            seen.add(manifest.name)

    def _check_valid_dependency_entries(self, manifests: list[PluginManifest]) -> None:
        for manifest in manifests:
            for dep in manifest.dependencies:
                if not isinstance(dep, str) or not dep.strip():
                    raise InvalidDependencyError(
                        f"plugin '{manifest.name}' declares an invalid "
                        f"dependency name: {dep!r}"
                    )
                if dep == manifest.name:
                    raise InvalidDependencyError(
                        f"plugin '{manifest.name}' cannot depend on itself"
                    )

    def _check_missing_dependencies(
        self, manifests: list[PluginManifest], known_names: set[str]
    ) -> None:
        for manifest in manifests:
            unknown = set(manifest.dependencies) - known_names
            if unknown:
                raise MissingDependencyError(
                    f"plugin '{manifest.name}' depends on unknown "
                    f"plugin(s): {sorted(unknown)}"
                )

    # -- topological sort (Kahn's Algorithm) --------------------------------

    def _topological_sort(self, known_names: set[str]) -> list[str]:
        """
        Kahn's Algorithm: repeatedly remove nodes with no unresolved
        dependencies (in-degree 0), appending each to the result and
        decrementing the in-degree of everything that depended on it.
        If every node is eventually removed, the result is a valid
        topological order. If any nodes remain, they -- and only they
        -- are involved in a cycle, since a cycle is exactly the
        condition under which no node in it ever reaches in-degree 0.
        """
        in_degree: dict[str, int] = {
            name: len(self._graph.get_dependencies(name)) for name in known_names
        }

        # Sorted processing order makes the result deterministic and
        # reproducible across runs, independent of dict iteration order.
        ready: deque[str] = deque(
            sorted(name for name, degree in in_degree.items() if degree == 0)
        )
        order: list[str] = []

        while ready:
            name = ready.popleft()
            order.append(name)
            for dependent in sorted(self._graph.get_dependents(name)):
                if dependent not in in_degree:
                    continue
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)

        if len(order) != len(known_names):
            unresolved = known_names - set(order)
            raise CircularDependencyError(
                f"circular dependency detected among plugin(s): {sorted(unresolved)}"
            )

        return order
