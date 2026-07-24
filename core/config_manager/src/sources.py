"""
Concrete ConfigSourcePort implementations.

Each loader flattens its source into dotted keys so all sources merge
uniformly regardless of origin, e.g. a nested YAML block:
    event_bus:
      queue_size: 500
becomes {"event_bus.queue_size": 500}, matching the same key an env var
SENTINEL_EVENT_BUS__QUEUE_SIZE would produce.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from domain.ports.config_port import ConfigSourcePort

logger = logging.getLogger("sentinel.config")

try:
    import yaml  # type: ignore
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover -- exercised only if PyYAML absent
    _YAML_AVAILABLE = False


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        else:
            flat[dotted] = value
    return flat


class JsonFileConfigSource(ConfigSourcePort):
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def name(self) -> str:
        return f"json:{self._path}"

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            logger.debug("no JSON config at %s, skipping", self._path)
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in config file {self._path}: {exc}") from exc
        return _flatten(raw)


class YamlFileConfigSource(ConfigSourcePort):
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def name(self) -> str:
        return f"yaml:{self._path}"

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            logger.debug("no YAML config at %s, skipping", self._path)
            return {}
        if not _YAML_AVAILABLE:
            raise RuntimeError(
                "PyYAML is not installed but a YAML config file was found "
                f"at {self._path}. Run: pip install PyYAML"
            )
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in config file {self._path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"YAML config at {self._path} must be a mapping at the top level")
        return _flatten(raw)


class EnvVarConfigSource(ConfigSourcePort):
    """
    Reads SENTINEL_* environment variables. Double underscore denotes
    nesting, e.g. SENTINEL_EVENT_BUS__QUEUE_SIZE -> "event_bus.queue_size".
    Env vars always win (SAD-aligned 12-factor precedence) since they're
    the one override you can make without touching a file on disk.
    """

    def __init__(self, prefix: str = "SENTINEL_") -> None:
        self._prefix = prefix

    @property
    def name(self) -> str:
        return f"env:{self._prefix}*"

    def load(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for env_key, value in os.environ.items():
            if not env_key.startswith(self._prefix):
                continue
            stripped = env_key[len(self._prefix):]
            dotted = stripped.lower().replace("__", ".")
            result[dotted] = value
        return result
