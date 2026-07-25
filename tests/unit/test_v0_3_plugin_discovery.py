"""
Unit tests for v0.3 Phase 1: Plugin Discovery.
Run with:  pytest tests/unit/test_v0_3_plugin_discovery.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.plugin_loader.exceptions import PluginManifestError
from core.plugin_loader.plugin_loader import PluginLoader
from core.plugin_loader.plugin_manifest import PluginManifest


def _write_manifest(folder: Path, data: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


VALID_MANIFEST = {
    "name": "weather",
    "version": "1.0.0",
    "author": "Test Author",
    "description": "A test plugin",
    "entry_point": "plugin:WeatherPlugin",
    "dependencies": [],
    "permissions": ["network.http"],
    "enabled": True,
}


# ---------------------------------------------------------------------------
# PluginManifest parsing
# ---------------------------------------------------------------------------

def test_parses_valid_manifest_dict():
    manifest = PluginManifest.from_dict(VALID_MANIFEST)
    assert manifest.name == "weather"
    assert str(manifest.version) == "1.0.0"
    assert manifest.entry_point == "plugin:WeatherPlugin"
    assert manifest.permissions == ("network.http",)
    assert manifest.enabled is True


def test_defaults_applied_for_optional_fields():
    minimal = {"name": "x", "version": "1.0.0", "entry_point": "plugin:X"}
    manifest = PluginManifest.from_dict(minimal)
    assert manifest.author == ""
    assert manifest.description == ""
    assert manifest.dependencies == ()
    assert manifest.permissions == ()
    assert manifest.enabled is True


@pytest.mark.parametrize("missing_field", ["name", "version", "entry_point"])
def test_missing_required_field_raises(missing_field):
    data = dict(VALID_MANIFEST)
    del data[missing_field]
    with pytest.raises(PluginManifestError, match="missing required field"):
        PluginManifest.from_dict(data)


def test_invalid_version_string_raises():
    data = dict(VALID_MANIFEST)
    data["version"] = "not-a-version"
    with pytest.raises(PluginManifestError, match="invalid version"):
        PluginManifest.from_dict(data)


def test_empty_entry_point_raises_as_missing_required_field():
    """An empty string is falsy, so it's correctly caught by the
    required-field check before ever reaching the type/format check."""
    data = dict(VALID_MANIFEST)
    data["entry_point"] = ""
    with pytest.raises(PluginManifestError, match="missing required field"):
        PluginManifest.from_dict(data)


def test_non_string_entry_point_raises_invalid_entry_point():
    """A present-but-wrong-type entry_point (e.g. a number) passes the
    required-field presence check but must still be rejected by the
    type/format check."""
    data = dict(VALID_MANIFEST)
    data["entry_point"] = 12345
    with pytest.raises(PluginManifestError, match="invalid entry_point"):
        PluginManifest.from_dict(data)


def test_dependencies_must_be_a_list():
    data = dict(VALID_MANIFEST)
    data["dependencies"] = "not-a-list"
    with pytest.raises(PluginManifestError, match="must be a list"):
        PluginManifest.from_dict(data)


def test_from_file_reads_and_parses(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path / "weather", VALID_MANIFEST)
    manifest = PluginManifest.from_file(manifest_path)
    assert manifest.name == "weather"
    assert manifest.source_dir == manifest_path.parent


def test_from_file_invalid_json_raises_plugin_manifest_error(tmp_path: Path):
    path = tmp_path / "broken" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(PluginManifestError, match="invalid JSON"):
        PluginManifest.from_file(path)


def test_from_file_non_object_json_raises(tmp_path: Path):
    path = tmp_path / "list_root" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(PluginManifestError, match="JSON object"):
        PluginManifest.from_file(path)


# ---------------------------------------------------------------------------
# PluginLoader.discover() -- happy paths
# ---------------------------------------------------------------------------

def test_discover_finds_single_valid_plugin(tmp_path: Path):
    _write_manifest(tmp_path / "weather", VALID_MANIFEST)

    loader = PluginLoader(tmp_path)
    discovered = loader.discover()

    assert len(discovered) == 1
    assert discovered[0].name == "weather"


def test_discover_finds_multiple_plugins(tmp_path: Path):
    _write_manifest(tmp_path / "weather", VALID_MANIFEST)
    calc_manifest = dict(VALID_MANIFEST, name="calculator", entry_point="plugin:CalculatorPlugin")
    _write_manifest(tmp_path / "calculator", calc_manifest)

    loader = PluginLoader(tmp_path)
    discovered = loader.discover()

    names = {m.name for m in discovered}
    assert names == {"weather", "calculator"}


def test_discover_is_recursive_into_nested_folders(tmp_path: Path):
    """Phase 1 explicitly requires recursive discovery -- a plugin
    nested under a category subfolder must still be found."""
    nested_manifest = dict(VALID_MANIFEST, name="nested_plugin", entry_point="plugin:NestedPlugin")
    _write_manifest(tmp_path / "integrations" / "nested_plugin", nested_manifest)

    loader = PluginLoader(tmp_path)
    discovered = loader.discover()

    assert len(discovered) == 1
    assert discovered[0].name == "nested_plugin"


def test_discover_returns_empty_list_for_empty_directory(tmp_path: Path):
    loader = PluginLoader(tmp_path)
    assert loader.discover() == []


def test_discover_returns_empty_list_for_nonexistent_directory(tmp_path: Path):
    loader = PluginLoader(tmp_path / "does_not_exist")
    assert loader.discover() == []


def test_discover_returns_empty_list_when_root_is_a_file(tmp_path: Path):
    file_path = tmp_path / "not_a_directory.txt"
    file_path.write_text("hello")
    loader = PluginLoader(file_path)
    assert loader.discover() == []


# ---------------------------------------------------------------------------
# PluginLoader.discover() -- graceful error handling
# ---------------------------------------------------------------------------

def test_discover_skips_invalid_manifest_but_keeps_valid_ones(tmp_path: Path):
    _write_manifest(tmp_path / "weather", VALID_MANIFEST)
    broken_dir = tmp_path / "broken_plugin"
    broken_dir.mkdir()
    (broken_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    loader = PluginLoader(tmp_path)
    discovered = loader.discover()

    assert len(discovered) == 1
    assert discovered[0].name == "weather"


def test_discover_skips_manifest_missing_required_field(tmp_path: Path):
    incomplete = {"name": "incomplete_plugin"}  # missing version, entry_point
    _write_manifest(tmp_path / "incomplete", incomplete)
    _write_manifest(tmp_path / "weather", VALID_MANIFEST)

    loader = PluginLoader(tmp_path)
    discovered = loader.discover()

    assert len(discovered) == 1
    assert discovered[0].name == "weather"


def test_discover_ignores_directories_without_manifest_json(tmp_path: Path):
    """Folders with no manifest.json at all (the normal case for any
    non-plugin directory) contribute nothing and cause no error."""
    empty_dir = tmp_path / "not_a_plugin"
    empty_dir.mkdir()
    (empty_dir / "readme.txt").write_text("just a file")

    loader = PluginLoader(tmp_path)
    assert loader.discover() == []


# ---------------------------------------------------------------------------
# Coexistence with the existing Module Registry (module.manifest.json)
# ---------------------------------------------------------------------------

def test_discover_ignores_module_registry_manifest_filename(tmp_path: Path):
    """A folder using module.manifest.json (the existing v0.1 Module
    Registry's filename) must be completely ignored by the Plugin
    Loader, which only ever looks for manifest.json."""
    module_dir = tmp_path / "security_manager"
    module_dir.mkdir()
    (module_dir / "module.manifest.json").write_text(
        json.dumps({"id": "security_manager", "version": "0.1.0"}), encoding="utf-8"
    )

    loader = PluginLoader(tmp_path)
    assert loader.discover() == []


def test_discover_against_real_modules_directory_finds_only_weather():
    """End-to-end proof against the actual project modules/ directory:
    security_manager/ and demo_echo/ (module.manifest.json) must be
    ignored; weather/ (manifest.json) must be found."""
    project_root = Path(__file__).resolve().parents[2]
    modules_dir = project_root / "modules"

    loader = PluginLoader(modules_dir)
    discovered = loader.discover()

    names = {m.name for m in discovered}
    assert "weather" in names
    assert "security_manager" not in names
    assert "demo_echo" not in names
