"""
Unit tests for v0.2's Configuration Manager.
Run with:  pytest tests/unit/test_v0_2_config_manager.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config_manager.src.config_manager import ConfigurationManager
from core.config_manager.src.sources import (
    EnvVarConfigSource,
    JsonFileConfigSource,
    YamlFileConfigSource,
)
from domain.entities.config_schema import ConfigField, ConfigSchema, ConfigValidationError


# ---------------------------------------------------------------------------
# Loading: JSON, YAML, missing files
# ---------------------------------------------------------------------------

def test_json_source_loads_and_flattens_nested_keys(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"event_bus": {"queue_size": 500}}))

    config = ConfigurationManager(sources=[JsonFileConfigSource(path)])
    assert config.get_int("event_bus.queue_size") == 500


def test_yaml_source_loads_and_flattens_nested_keys(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("event_bus:\n  queue_size: 750\n")

    config = ConfigurationManager(sources=[YamlFileConfigSource(path)])
    assert config.get_int("event_bus.queue_size") == 750


def test_missing_config_file_is_not_an_error(tmp_path: Path):
    """A missing optional config source returns {} rather than raising --
    absence is normal (e.g. no local.yaml override present)."""
    missing = tmp_path / "does_not_exist.json"
    config = ConfigurationManager(sources=[JsonFileConfigSource(missing)])
    assert config.all_values() == {}


def test_invalid_json_raises_clear_error(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json")

    with pytest.raises(ValueError, match="invalid JSON"):
        ConfigurationManager(sources=[JsonFileConfigSource(path)])


def test_invalid_yaml_raises_clear_error(tmp_path: Path):
    path = tmp_path / "broken.yaml"
    path.write_text("event_bus: [unclosed\n")

    with pytest.raises(ValueError, match="invalid YAML"):
        ConfigurationManager(sources=[YamlFileConfigSource(path)])


def test_yaml_top_level_must_be_a_mapping(tmp_path: Path):
    path = tmp_path / "list.yaml"
    path.write_text("- item_one\n- item_two\n")

    with pytest.raises(ValueError, match="must be a mapping"):
        ConfigurationManager(sources=[YamlFileConfigSource(path)])


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_default_values_used_when_key_absent():
    config = ConfigurationManager(sources=[])
    assert config.get_int("nonexistent.key", default=99) == 99
    assert config.get_str("nonexistent.key", default="fallback") == "fallback"
    assert config.get_bool("nonexistent.key", default=True) is True


def test_schema_default_applied_when_source_omits_key():
    schema = ConfigSchema(fields=(
        ConfigField(key="event_bus.queue_size", type=int, default=250),
    ))
    config = ConfigurationManager(sources=[], schema=schema)
    assert config.get_int("event_bus.queue_size") == 250


# ---------------------------------------------------------------------------
# Precedence: env vars override files
# ---------------------------------------------------------------------------

def test_env_var_overrides_json_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"event_bus": {"queue_size": 1000}}))
    monkeypatch.setenv("SENTINEL_EVENT_BUS__QUEUE_SIZE", "42")

    config = ConfigurationManager(sources=[
        JsonFileConfigSource(path),
        EnvVarConfigSource(),
    ])
    assert config.get_int("event_bus.queue_size") == 42


def test_yaml_overrides_json_when_yaml_listed_later(tmp_path: Path):
    json_path = tmp_path / "config.json"
    json_path.write_text(json.dumps({"event_bus": {"queue_size": 1000}}))
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("event_bus:\n  queue_size: 500\n")

    config = ConfigurationManager(sources=[
        JsonFileConfigSource(json_path),
        YamlFileConfigSource(yaml_path),
    ])
    assert config.get_int("event_bus.queue_size") == 500


def test_runtime_override_applies_immediately():
    config = ConfigurationManager(sources=[])
    config.set_override("feature.flag", True)
    assert config.get_bool("feature.flag") is True

    config.clear_override("feature.flag")
    assert config.get_bool("feature.flag", default=False) is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_required_field_missing_raises():
    schema = ConfigSchema(fields=(
        ConfigField(key="security.audit_log_path", type=str, required=True),
    ))
    with pytest.raises(ConfigValidationError, match="required config key"):
        ConfigurationManager(sources=[], schema=schema)


def test_type_coercion_from_string_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SENTINEL_EVENT_BUS__QUEUE_SIZE", "300")
    schema = ConfigSchema(fields=(
        ConfigField(key="event_bus.queue_size", type=int),
    ))
    config = ConfigurationManager(sources=[EnvVarConfigSource()], schema=schema)
    assert config.get_int("event_bus.queue_size") == 300
    assert isinstance(config.get("event_bus.queue_size"), int)


def test_bool_coercion_from_string():
    schema = ConfigSchema(fields=(
        ConfigField(key="feature.enabled", type=bool),
    ))
    config = ConfigurationManager(
        sources=[JsonFileConfigSource(Path("/nonexistent"))],
        schema=schema,
    )
    config.set_override("feature.enabled", "true")
    assert config.get_bool("feature.enabled") is True


def test_custom_validator_rejects_out_of_range_value():
    schema = ConfigSchema(fields=(
        ConfigField(
            key="event_bus.queue_size",
            type=int,
            default=1000,
            validator=lambda v: v > 0,
        ),
    ))
    config = ConfigurationManager(sources=[], schema=schema)
    with pytest.raises(ConfigValidationError, match="failed validation"):
        config.set_override("event_bus.queue_size", -5)


def test_reload_keeps_previous_config_on_validation_failure():
    schema = ConfigSchema(fields=(
        ConfigField(key="event_bus.queue_size", type=int, default=1000, validator=lambda v: v > 0),
    ))
    config = ConfigurationManager(sources=[], schema=schema)
    assert config.get_int("event_bus.queue_size") == 1000

    with pytest.raises(ConfigValidationError):
        config.set_override("event_bus.queue_size", -1)

    # previous good value must still be in effect after a failed reload
    assert config.get_int("event_bus.queue_size") == 1000


def test_rejected_override_does_not_poison_later_reloads():
    """A rejected set_override() call must roll back cleanly -- it must
    not leave the bad value sitting in runtime overrides where it would
    keep failing validation on every subsequent, unrelated reload()."""
    schema = ConfigSchema(fields=(
        ConfigField(key="event_bus.queue_size", type=int, default=1000, validator=lambda v: v > 0),
    ))
    config = ConfigurationManager(sources=[], schema=schema)

    with pytest.raises(ConfigValidationError):
        config.set_override("event_bus.queue_size", -1)

    # an unrelated, valid override must succeed afterwards
    config.set_override("some.other.key", "fine")
    assert config.get_int("event_bus.queue_size") == 1000
    assert config.get_str("some.other.key") == "fine"


# ---------------------------------------------------------------------------
# Integration: Kernel + Event Bus pick up config-driven values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kernel_reads_queue_size_from_config(tmp_path: Path):
    from core.kernel.kernel import Kernel
    from domain.entities.event import Priority
    from modules.security_manager.src.security_manager import SecurityManager

    config = ConfigurationManager(sources=[])
    config.set_override("event_bus.queue_size", 7)

    security = SecurityManager(
        granted_scopes_path=tmp_path / "granted.json",
        audit_log_path=tmp_path / "audit.log",
    )
    kernel = Kernel(security=security, config=config)

    assert kernel.event_bus._queues[Priority.NORMAL].maxsize == 7
    await kernel.start()
    await kernel.stop()


@pytest.mark.asyncio
async def test_kernel_without_config_still_works_unchanged(tmp_path: Path):
    """Backward compatibility: Kernel(security=...) with no config arg
    must behave exactly as it did before v0.2 introduced config."""
    from core.kernel.kernel import Kernel
    from modules.security_manager.src.security_manager import SecurityManager

    security = SecurityManager(
        granted_scopes_path=tmp_path / "granted.json",
        audit_log_path=tmp_path / "audit.log",
    )
    kernel = Kernel(security=security)  # no config kwarg at all
    await kernel.start()
    await kernel.stop()
    assert kernel.config is None
