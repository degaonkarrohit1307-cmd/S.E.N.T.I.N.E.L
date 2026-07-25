"""
Plugin system exceptions.

Phase 1 (discovery) only needs PluginManifestError -- raised when a
manifest.json exists but can't be parsed into a valid PluginManifest
(malformed JSON, or missing a required field).

This is deliberately the base of what will become a fuller hierarchy in
later phases (duplicate names, missing entry points, dependency cycles,
lifecycle errors, etc.) -- those subclasses get added when their phase
is built, not speculatively now.
"""
from __future__ import annotations


class PluginError(Exception):
    """Base class for all plugin-system errors."""


class PluginManifestError(PluginError):
    """Raised when a manifest.json is malformed or missing a required
    field. During discovery, this is caught and logged -- the offending
    directory is skipped rather than aborting the whole scan."""
