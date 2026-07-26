"""
Plugin system exceptions.

Phase 1 (discovery) introduced PluginManifestError -- raised when a
manifest.json exists but can't be parsed into a valid PluginManifest
(malformed JSON, or missing a required field).

Phase v0.3.2 (lifecycle) added InvalidPluginStateError and its two more
specific subclasses, PluginAlreadyRunningError and PluginNotLoadedError,
used by PluginLifecycleManager to reject illegal state transitions.

Phase v0.3.3 (dependency resolution) adds PluginDependencyError and its
four more specific subclasses -- DuplicatePluginError,
InvalidDependencyError, MissingDependencyError, and
CircularDependencyError -- used by DependencyResolver to reject invalid
dependency graphs before any plugin is loaded.
"""
from __future__ import annotations


class PluginError(Exception):
    """Base class for all plugin-system errors."""


class PluginManifestError(PluginError):
    """Raised when a manifest.json is malformed or missing a required
    field. During discovery, this is caught and logged -- the offending
    directory is skipped rather than aborting the whole scan."""


class InvalidPluginStateError(PluginError):
    """Raised when a lifecycle transition is attempted from a state
    that does not permit it -- e.g. jumping straight from DISCOVERED to
    RUNNING, repeating a transition that already landed on its target
    state, or attempting any transition out of a terminal state
    (FAILED or UNLOADED). This is the general-purpose lifecycle error;
    PluginAlreadyRunningError and PluginNotLoadedError below are more
    specific subclasses raised for particular, common cases so callers
    can catch precisely what they care about while still being able to
    catch InvalidPluginStateError broadly."""


class PluginAlreadyRunningError(InvalidPluginStateError):
    """Raised when start_plugin() is called on a plugin that is already
    in the RUNNING state (a duplicate start)."""


class PluginNotLoadedError(InvalidPluginStateError):
    """Raised when a lifecycle operation beyond load_plugin() is
    attempted on a plugin that has never been loaded (still in
    DISCOVERED state), or on a plugin name that was never registered
    with the lifecycle manager at all -- both cases mean "this plugin
    has not been loaded," just for two different reasons."""


class PluginDependencyError(PluginError):
    """Base class for all dependency-resolution errors, raised by
    DependencyResolver while validating a set of discovered manifests
    and computing a safe loading order. Catch this broadly to handle
    "the dependency graph is invalid in some way," or catch one of the
    four subclasses below to handle a specific, distinct cause."""


class DuplicatePluginError(PluginDependencyError):
    """Raised when two or more manifests given to DependencyResolver
    share the same plugin name. This is distinct from a plugin listing
    the same dependency name twice within its own `dependencies` list
    (which is harmless and silently deduplicated by DependencyGraph) --
    this error is specifically about two different plugins colliding on
    identity."""


class InvalidDependencyError(PluginDependencyError):
    """Raised when a manifest declares a dependency that is malformed
    on its face, independent of whether the referenced plugin exists:
    a self-dependency (a plugin depending on its own name), or a
    blank/non-string dependency entry."""


class MissingDependencyError(PluginDependencyError):
    """Raised when a manifest depends on a plugin name that is not
    present among the set of manifests given to DependencyResolver --
    the dependency itself is well-formed, but the plugin it names was
    never discovered."""


class CircularDependencyError(PluginDependencyError):
    """Raised when the dependency graph contains a cycle spanning two
    or more plugins (e.g. A depends on B, B depends on A), detected via
    Kahn's Algorithm: if any nodes remain unprocessed after the
    algorithm terminates, those nodes form (or are part of) a cycle."""
