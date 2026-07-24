"""
Domain port: ConfigSourcePort

Each concrete loader (JSON file, YAML file, environment variables)
implements this. ConfigurationManager depends only on this interface,
never on json/yaml/os directly -- new source types (e.g. a remote config
service later) are new adapters, not core changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConfigSourcePort(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]:
        """Return a flat dict of dotted-key -> value. Missing/absent
        sources (e.g. no config file present) return {} rather than
        raising -- absence is normal, not exceptional, for optional
        sources like a local override file."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable source name, used in precedence logging."""
