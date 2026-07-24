"""
ConfigurationManager

Merges configuration from multiple sources by precedence, validates the
merged result against a ConfigSchema, and exposes type-safe access.

Precedence (highest wins): env vars > runtime overrides > YAML > JSON
> schema defaults. This is standard 12-factor ordering: env vars are the
one thing changeable without touching a file, so they must win.

Hot reload is DESIGNED for but not wired to a file-watcher in v0.2
(explicit scope control -- see docs/adr/0003). `reload()` can be called
manually right now; automatic invocation on file-change is a v0.3+
concern layered on top without changing this class's shape.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from domain.entities.config_schema import ConfigSchema, ConfigValidationError
from domain.ports.config_port import ConfigSourcePort
from domain.ports.system_ports import EventBusPort
from domain.entities.event import Event, Priority

logger = logging.getLogger("sentinel.config_manager")

_UNSET = object()  # sentinel distinct from any real config value, incl. None


class ConfigurationManager:
    def __init__(
        self,
        sources: list[ConfigSourcePort],
        schema: Optional[ConfigSchema] = None,
        event_bus: Optional[EventBusPort] = None,
    ) -> None:
        """
        `sources` must be given in ASCENDING precedence order (lowest
        priority first), e.g.:
            [JsonFileConfigSource(...), YamlFileConfigSource(...), EnvVarConfigSource()]
        Later sources in the list override earlier ones on key collision.
        Runtime overrides (set_override) apply on top of all sources but
        below any env var already present -- see set_override docstring.
        """
        self._sources = sources
        self._schema = schema or ConfigSchema()
        self._event_bus = event_bus
        self._runtime_overrides: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self.reload()

    # -- public API ---------------------------------------------------------

    def reload(self) -> None:
        """Re-read every source and re-validate. Safe to call at any
        time; on validation failure the PREVIOUS good config is kept and
        the error is re-raised, so a bad edit to a file never leaves the
        running system with a half-applied or empty config."""
        merged: dict[str, Any] = {}
        for source in self._sources:
            try:
                data = source.load()
            except Exception:
                logger.exception("failed to load config source %s", source.name)
                raise
            merged.update(data)
            logger.debug("merged config source %s (%d keys)", source.name, len(data))

        merged.update(self._runtime_overrides)

        try:
            validated = self._schema.validate_all(merged)
        except ConfigValidationError:
            logger.exception(
                "config validation failed on reload; keeping previous config"
            )
            raise

        previous = self._values
        self._values = validated
        logger.info("configuration reloaded (%d keys)", len(validated))
        if previous != validated and self._event_bus is not None:
            self._publish_changed(previous, validated)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def get_str(self, key: str, default: str = "") -> str:
        return str(self._values.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self._values.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self._values.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    def get_float(self, key: str, default: float = 0.0) -> float:
        return float(self._values.get(key, default))

    def set_override(self, key: str, value: Any) -> None:
        """Runtime override -- e.g. a Settings UI change that should
        apply immediately without editing a file. Applied after all file
        sources are merged, so it wins over JSON/YAML; a subsequent
        reload() will still let a genuinely present env var win, since
        env vars represent operator/deploy-level intent that an in-app
        setting should not silently clobber."""
        previous_override = self._runtime_overrides.get(key, _UNSET)
        self._runtime_overrides[key] = value
        try:
            self.reload()
        except ConfigValidationError:
            # Roll back this specific override rather than leaving a
            # rejected value sitting in _runtime_overrides, where it
            # would otherwise keep failing validation on every future,
            # unrelated reload() call until manually cleared.
            if previous_override is _UNSET:
                self._runtime_overrides.pop(key, None)
            else:
                self._runtime_overrides[key] = previous_override
            raise

    def clear_override(self, key: str) -> None:
        self._runtime_overrides.pop(key, None)
        self.reload()

    def all_values(self) -> dict[str, Any]:
        return dict(self._values)

    # -- internals ------------------------------------------------------------

    def _publish_changed(self, previous: dict[str, Any], current: dict[str, Any]) -> None:
        changed_keys = {
            key for key in set(previous) | set(current)
            if previous.get(key) != current.get(key)
        }
        if not changed_keys or self._event_bus is None:
            return
        # ConfigurationManager itself is synchronous (config load is not
        # on the hot path), but the bus is async -- schedule the publish
        # rather than requiring reload() to become async everywhere.
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._event_bus.publish(
                    Event(
                        type="config.changed",
                        source="config_manager",
                        payload={"changed_keys": sorted(changed_keys)},
                        priority=Priority.NORMAL,
                    )
                )
            )
        except RuntimeError:
            # No running event loop (e.g. called from sync test/CLI code)
            # -- fine, config.changed is a notification, not a
            # requirement for reload() to succeed.
            logger.debug("no running event loop; skipping config.changed publish")
