"""
DependencyGraph -- a directed graph of plugin dependencies.

Each plugin is a node. Each dependency is a directed edge from the
dependent plugin to the plugin it depends on. This is a pure data
structure with no knowledge of PluginManifest, resolution algorithms,
or error semantics -- DependencyResolver owns validation and
topological sorting; this class only stores and answers questions
about the graph shape.

Kept deliberately decoupled from PluginManifest (build_graph() accepts
plain (name, dependencies) pairs) so it can be tested, reused, and
reasoned about independently of the plugin manifest schema.
"""
from __future__ import annotations

from typing import Iterable


class DependencyGraph:
    """
    Directed graph of plugin dependency edges, with O(1) lookup of both
    a node's dependencies and its dependents.
    """

    def __init__(self) -> None:
        self._dependencies: dict[str, set[str]] = {}
        self._dependents: dict[str, set[str]] = {}

    def add_plugin(self, name: str, dependencies: Iterable[str] = ()) -> None:
        """
        Register a plugin node and its declared dependency edges.

        Safe to call more than once for the same `name`: doing so
        replaces that plugin's previous outgoing edges entirely (any
        stale reverse-edges from a prior call are cleaned up first)
        rather than merging old and new dependency sets together.

        A `name` appearing in `dependencies` before it has been added
        as its own node is fine -- `get_dependents()` and later
        `add_plugin()` calls for that name both work correctly
        regardless of insertion order, since dependents are recorded
        via `setdefault`.
        """
        previous = self._dependencies.get(name)
        if previous:
            for old_dep in previous:
                self._dependents.get(old_dep, set()).discard(name)

        self._dependencies[name] = set()
        self._dependents.setdefault(name, set())

        for dep in dependencies:
            self._dependencies[name].add(dep)
            self._dependents.setdefault(dep, set())
            self._dependents[dep].add(name)

    def remove_plugin(self, name: str) -> None:
        """
        Remove a plugin node and every edge referencing it in either
        direction (as a dependency of something else, and as something
        that depends on other plugins). Safe to call on an unknown
        name -- this is a no-op, not an error.
        """
        outgoing = self._dependencies.pop(name, set())
        for dep in outgoing:
            self._dependents.get(dep, set()).discard(name)

        incoming = self._dependents.pop(name, set())
        for dependent in incoming:
            self._dependencies.get(dependent, set()).discard(name)

    def get_dependencies(self, name: str) -> frozenset[str]:
        """Return the set of plugin names `name` directly depends on.
        Returns an empty frozenset for an unknown or dependency-free name."""
        return frozenset(self._dependencies.get(name, set()))

    def get_dependents(self, name: str) -> frozenset[str]:
        """Return the set of plugin names that directly depend on
        `name`. Returns an empty frozenset if nothing depends on it,
        including if `name` itself was never added as its own node
        (e.g. it is only known as someone else's dependency target)."""
        return frozenset(self._dependents.get(name, set()))

    def nodes(self) -> frozenset[str]:
        """Return every plugin name explicitly registered via
        add_plugin()/build_graph() -- this deliberately does NOT
        include names that only appear as a dependency target of some
        other plugin but were never themselves added as a node, which
        is exactly what lets a caller compute "missing dependencies" as
        the set difference between declared dependency targets and
        this method's result."""
        return frozenset(self._dependencies.keys())

    def build_graph(self, plugins: Iterable[tuple[str, Iterable[str]]]) -> None:
        """
        Bulk-construct the graph from an iterable of
        (plugin_name, dependencies) pairs, discarding any previously
        held graph contents entirely first.
        """
        self._dependencies = {}
        self._dependents = {}
        for name, deps in plugins:
            self.add_plugin(name, deps)
