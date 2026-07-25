"""
Plugin system exceptions.

Phase 1 (discovery) introduced PluginManifestError -- raised when a
manifest.json exists but can't be parsed into a valid PluginManifest
(malformed JSON, or missing a required field).

Phase v0.3.2 (lifecycle) adds InvalidPluginStateError and its two more
specific subclasses, PluginAlreadyRunningError and PluginNotLoadedError,
used by PluginLifecycleManager to reject illegal state transitions.

This remains the base of what will become a fuller hierarchy in later
phases (duplicate names, missing entry points, dependency cycles, etc.)
-- those subclasses get added when their phase is built, not
speculatively now.
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
