"""
Domain entities: ConfigField, ConfigSchema

Framework-free description of what configuration a component expects:
key, expected type, whether it's required, and its default. No
knowledge of JSON/YAML/env vars lives here -- that's Infrastructure's
job (core/config_manager/src/sources.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type


class ConfigValidationError(Exception):
    """Raised when a loaded config value fails schema validation."""


@dataclass(frozen=True)
class ConfigField:
    key: str                              # dotted path, e.g. "event_bus.queue_size"
    type: Type                            # expected Python type after coercion
    required: bool = False
    default: Any = None
    validator: Optional[Callable[[Any], bool]] = None
    description: str = ""

    def validate(self, value: Any) -> Any:
        if value is None:
            if self.required:
                raise ConfigValidationError(f"required config key '{self.key}' is missing")
            return self.default
        coerced = self._coerce(value)
        if self.validator is not None and not self.validator(coerced):
            raise ConfigValidationError(
                f"config key '{self.key}' failed validation: value={coerced!r}"
            )
        return coerced

    def _coerce(self, value: Any) -> Any:
        # Environment variables and JSON/YAML scalars sometimes arrive as
        # strings even when the schema expects int/bool/float -- coerce
        # rather than reject, since "queue_size=1000" from an env var is
        # a completely normal, valid input, not a type error.
        if self.type is bool and isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
            raise ConfigValidationError(
                f"config key '{self.key}' expected bool-like string, got {value!r}"
            )
        if self.type in (int, float) and isinstance(value, str):
            try:
                return self.type(value)
            except ValueError as exc:
                raise ConfigValidationError(
                    f"config key '{self.key}' expected {self.type.__name__}, got {value!r}"
                ) from exc
        if not isinstance(value, self.type):
            raise ConfigValidationError(
                f"config key '{self.key}' expected type {self.type.__name__}, "
                f"got {type(value).__name__}"
            )
        return value


@dataclass(frozen=True)
class ConfigSchema:
    fields: tuple[ConfigField, ...] = field(default_factory=tuple)

    def field_for(self, key: str) -> Optional[ConfigField]:
        return next((f for f in self.fields if f.key == key), None)

    def validate_all(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate every schema-declared field against raw (already
        merged, precedence-resolved) values. Keys not in the schema pass
        through unvalidated -- the schema declares what MUST be correct,
        not an exhaustive whitelist, so modules can carry ad hoc settings
        without every one needing a formal ConfigField up front."""
        result = dict(raw)
        for f in self.fields:
            result[f.key] = f.validate(raw.get(f.key))
        return result
