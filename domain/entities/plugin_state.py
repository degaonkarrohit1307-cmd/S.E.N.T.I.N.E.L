"""
PluginState -- the finite set of states a plugin can occupy during its
lifecycle.

Framework-free (no dependency on core/ or infrastructure), consistent
with the rest of domain/entities/*.
"""
from __future__ import annotations

from enum import Enum


class PluginState(str, Enum):
    """
    Valid plugin lifecycle states.

    The normal, successful path is strictly linear:

        DISCOVERED -> LOADED -> INITIALIZED -> RUNNING -> STOPPED -> UNLOADED

    FAILED is reachable from any non-terminal state if a lifecycle hook
    raises an exception during a transition. FAILED and UNLOADED are
    both terminal in this phase -- no further transitions are defined
    out of either. See docs/adr/0005-v0.3.2-plugin-lifecycle.md for the
    rationale and what a future "recover/reload" phase would add.
    """

    DISCOVERED = "discovered"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    UNLOADED = "unloaded"
