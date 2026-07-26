"""
Unit tests for v0.3.3: Plugin Dependency Resolution.
Run with:  pytest tests/unit/test_v0_3_3_dependency_resolution.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.plugin_loader.dependency_graph import DependencyGraph
from core.plugin_loader.dependency_resolver import DependencyResolver
from core.plugin_loader.exceptions import (
    CircularDependencyError,
    DuplicatePluginError,
    InvalidDependencyError,
    MissingDependencyError,
    PluginDependencyError,
)
from core.plugin_loader.plugin_loader import PluginLoader
from core.plugin_loader.plugin_manifest import PluginManifest
from domain.entities.plugin_dependency import PluginDependency


def _manifest(name: str, dependencies: list[str] | None = None) -> PluginManifest:
    return PluginManifest.from_dict({
        "name": name,
        "version": "1.0.0",
        "entry_point": f"plugin:{name.title()}Plugin",
        "dependencies": dependencies or [],
    })


def _write_manifest(folder: Path, data: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# PluginDependency (domain entity)
# ---------------------------------------------------------------------------

def test_plugin_dependency_is_a_plain_equatable_value_object():
    a = PluginDependency(plugin_name="weather", depends_on="network_manager")
    b = PluginDependency(plugin_name="weather", depends_on="network_manager")
    c = PluginDependency(plugin_name="weather", depends_on="security_manager")
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# DependencyGraph: add_plugin / remove_plugin / get_dependencies / get_dependents
# ---------------------------------------------------------------------------

def test_add_plugin_with_no_dependencies():
    graph = DependencyGraph()
    graph.add_plugin("weather", [])
    assert graph.get_dependencies("weather") == frozenset()
    assert graph.nodes() == frozenset({"weather"})


def test_add_plugin_with_single_dependency():
    graph = DependencyGraph()
    graph.add_plugin("weather", ["security_manager"])
    assert graph.get_dependencies("weather") == frozenset({"security_manager"})
    assert graph.get_dependents("security_manager") == frozenset({"weather"})


def test_add_plugin_with_multiple_dependencies():
    graph = DependencyGraph()
    graph.add_plugin("weather", ["security_manager", "network_manager"])
    assert graph.get_dependencies("weather") == frozenset(
        {"security_manager", "network_manager"}
    )


def test_get_dependencies_unknown_node_returns_empty_frozenset():
    graph = DependencyGraph()
    assert graph.get_dependencies("nonexistent") == frozenset()


def test_get_dependents_unknown_node_returns_empty_frozenset():
    graph = DependencyGraph()
    assert graph.get_dependents("nonexistent") == frozenset()


def test_dependents_recorded_even_before_target_added_as_its_own_node():
    """weather depends on network_manager, which hasn't been add_plugin()'d
    yet in its own right -- get_dependents must still work."""
    graph = DependencyGraph()
    graph.add_plugin("weather", ["network_manager"])
    assert graph.get_dependents("network_manager") == frozenset({"weather"})
    assert "network_manager" not in graph.nodes()


def test_re_adding_a_plugin_replaces_its_dependencies_not_merges():
    graph = DependencyGraph()
    graph.add_plugin("weather", ["security_manager"])
    graph.add_plugin("weather", ["network_manager"])

    assert graph.get_dependencies("weather") == frozenset({"network_manager"})
    assert graph.get_dependents("security_manager") == frozenset()


def test_remove_plugin_removes_node_and_outgoing_edges():
    graph = DependencyGraph()
    graph.add_plugin("security_manager", [])
    graph.add_plugin("weather", ["security_manager"])

    graph.remove_plugin("weather")

    assert "weather" not in graph.nodes()
    assert graph.get_dependents("security_manager") == frozenset()


def test_remove_plugin_removes_incoming_edges_from_dependents():
    graph = DependencyGraph()
    graph.add_plugin("security_manager", [])
    graph.add_plugin("weather", ["security_manager"])

    graph.remove_plugin("security_manager")

    assert "security_manager" not in graph.nodes()
    assert graph.get_dependencies("weather") == frozenset()


def test_remove_plugin_on_unknown_name_is_a_no_op():
    graph = DependencyGraph()
    graph.add_plugin("weather", [])
    graph.remove_plugin("nonexistent")
    assert graph.nodes() == frozenset({"weather"})


def test_build_graph_constructs_from_pairs_and_replaces_previous_contents():
    graph = DependencyGraph()
    graph.add_plugin("stale_plugin", [])

    graph.build_graph([
        ("weather", ["security_manager"]),
        ("security_manager", []),
    ])

    assert "stale_plugin" not in graph.nodes()
    assert graph.nodes() == frozenset({"weather", "security_manager"})
    assert graph.get_dependencies("weather") == frozenset({"security_manager"})


# ---------------------------------------------------------------------------
# DependencyResolver: happy paths
# ---------------------------------------------------------------------------

def test_resolve_plugin_with_no_dependencies():
    resolver = DependencyResolver()
    order = resolver.resolve([_manifest("weather")])
    assert order == ["weather"]


def test_resolve_single_dependency_orders_dependency_first():
    resolver = DependencyResolver()
    order = resolver.resolve([
        _manifest("weather", ["security_manager"]),
        _manifest("security_manager"),
    ])
    assert order.index("security_manager") < order.index("weather")


def test_resolve_multiple_dependencies_all_precede_dependent():
    resolver = DependencyResolver()
    order = resolver.resolve([
        _manifest("weather", ["security_manager", "network_manager"]),
        _manifest("security_manager"),
        _manifest("network_manager"),
    ])
    assert order.index("security_manager") < order.index("weather")
    assert order.index("network_manager") < order.index("weather")
    assert len(order) == 3


def test_resolve_deep_dependency_chain_preserves_order():
    resolver = DependencyResolver()
    order = resolver.resolve([
        _manifest("a", ["b"]),
        _manifest("b", ["c"]),
        _manifest("c", ["d"]),
        _manifest("d"),
    ])
    assert order == ["d", "c", "b", "a"]


def test_resolve_disconnected_graph_includes_all_nodes():
    resolver = DependencyResolver()
    order = resolver.resolve([
        _manifest("weather", ["security_manager"]),
        _manifest("security_manager"),
        _manifest("calculator", ["math_lib"]),
        _manifest("math_lib"),
    ])
    assert set(order) == {"weather", "security_manager", "calculator", "math_lib"}
    assert order.index("security_manager") < order.index("weather")
    assert order.index("math_lib") < order.index("calculator")


def test_resolve_diamond_dependency_graph():
    resolver = DependencyResolver()
    order = resolver.resolve([
        _manifest("weather", ["security_manager", "network_manager"]),
        _manifest("security_manager", ["core_utils"]),
        _manifest("network_manager", ["core_utils"]),
        _manifest("core_utils"),
    ])
    assert order[0] == "core_utils"
    assert order[-1] == "weather"
    assert len(order) == 4


def test_resolve_returns_deterministic_order_across_multiple_calls():
    manifests = [
        _manifest("weather", ["security_manager", "network_manager"]),
        _manifest("security_manager"),
        _manifest("network_manager"),
    ]
    first = DependencyResolver().resolve(list(manifests))
    second = DependencyResolver().resolve(list(manifests))
    assert first == second


def test_duplicate_dependency_entry_within_one_manifest_is_harmless():
    resolver = DependencyResolver()
    order = resolver.resolve([
        _manifest("weather", ["security_manager", "security_manager"]),
        _manifest("security_manager"),
    ])
    assert set(order) == {"weather", "security_manager"}
    assert order.index("security_manager") < order.index("weather")


# ---------------------------------------------------------------------------
# DependencyResolver: error paths
# ---------------------------------------------------------------------------

def test_resolver_graph_property_exposes_underlying_graph_after_resolve():
    resolver = DependencyResolver()
    resolver.resolve([
        _manifest("weather", ["security_manager"]),
        _manifest("security_manager"),
    ])
    assert resolver.graph.get_dependencies("weather") == frozenset({"security_manager"})


def test_missing_dependency_raises_missing_dependency_error():
    resolver = DependencyResolver()
    with pytest.raises(MissingDependencyError, match="unknown"):
        resolver.resolve([_manifest("weather", ["network_manager"])])


def test_duplicate_plugin_name_raises_duplicate_plugin_error():
    resolver = DependencyResolver()
    with pytest.raises(DuplicatePluginError, match="duplicate plugin name"):
        resolver.resolve([_manifest("weather"), _manifest("weather")])


def test_self_dependency_raises_invalid_dependency_error():
    resolver = DependencyResolver()
    with pytest.raises(InvalidDependencyError, match="cannot depend on itself"):
        resolver.resolve([_manifest("weather", ["weather"])])


def test_blank_dependency_name_raises_invalid_dependency_error():
    resolver = DependencyResolver()
    with pytest.raises(InvalidDependencyError, match="invalid dependency name"):
        resolver.resolve([_manifest("weather", [""])])


def test_two_node_circular_dependency_raises_circular_dependency_error():
    resolver = DependencyResolver()
    with pytest.raises(CircularDependencyError, match="circular dependency"):
        resolver.resolve([
            _manifest("a", ["b"]),
            _manifest("b", ["a"]),
        ])


def test_three_node_circular_dependency_raises_circular_dependency_error():
    resolver = DependencyResolver()
    with pytest.raises(CircularDependencyError):
        resolver.resolve([
            _manifest("a", ["b"]),
            _manifest("b", ["c"]),
            _manifest("c", ["a"]),
        ])


def test_circular_dependency_error_names_only_the_cycle_not_unrelated_nodes():
    resolver = DependencyResolver()
    with pytest.raises(CircularDependencyError) as exc_info:
        resolver.resolve([
            _manifest("a", ["b"]),
            _manifest("b", ["a"]),
            _manifest("standalone"),
        ])
    assert "standalone" not in str(exc_info.value)
    assert "a" in str(exc_info.value) and "b" in str(exc_info.value)


def test_all_dependency_errors_are_plugin_dependency_errors():
    resolver = DependencyResolver()
    with pytest.raises(PluginDependencyError):
        resolver.resolve([_manifest("weather", ["missing"])])
    with pytest.raises(PluginDependencyError):
        resolver.resolve([_manifest("weather"), _manifest("weather")])
    with pytest.raises(PluginDependencyError):
        resolver.resolve([_manifest("weather", ["weather"])])
    with pytest.raises(PluginDependencyError):
        resolver.resolve([_manifest("a", ["b"]), _manifest("b", ["a"])])


# ---------------------------------------------------------------------------
# PluginLoader integration
# ---------------------------------------------------------------------------

def test_discover_in_dependency_order_returns_manifests_not_just_names(tmp_path: Path):
    _write_manifest(tmp_path / "weather", {
        "name": "weather",
        "version": "1.0.0",
        "entry_point": "plugin:WeatherPlugin",
        "dependencies": ["security_manager"],
    })
    _write_manifest(tmp_path / "security_manager", {
        "name": "security_manager",
        "version": "1.0.0",
        "entry_point": "plugin:SecurityManagerPlugin",
        "dependencies": [],
    })

    loader = PluginLoader(tmp_path)
    ordered = loader.discover_in_dependency_order()

    assert [m.name for m in ordered] == ["security_manager", "weather"]
    assert all(isinstance(m, PluginManifest) for m in ordered)


def test_discover_in_dependency_order_with_no_dependencies_anywhere(tmp_path: Path):
    _write_manifest(tmp_path / "weather", {
        "name": "weather", "version": "1.0.0", "entry_point": "plugin:WeatherPlugin",
    })
    _write_manifest(tmp_path / "calculator", {
        "name": "calculator", "version": "1.0.0", "entry_point": "plugin:CalculatorPlugin",
    })

    loader = PluginLoader(tmp_path)
    ordered = loader.discover_in_dependency_order()

    assert {m.name for m in ordered} == {"weather", "calculator"}


def test_discover_in_dependency_order_raises_on_missing_dependency(tmp_path: Path):
    _write_manifest(tmp_path / "weather", {
        "name": "weather",
        "version": "1.0.0",
        "entry_point": "plugin:WeatherPlugin",
        "dependencies": ["network_manager"],
    })

    loader = PluginLoader(tmp_path)
    with pytest.raises(MissingDependencyError):
        loader.discover_in_dependency_order()


def test_discover_in_dependency_order_raises_on_circular_dependency(tmp_path: Path):
    _write_manifest(tmp_path / "a", {
        "name": "a", "version": "1.0.0", "entry_point": "plugin:A", "dependencies": ["b"],
    })
    _write_manifest(tmp_path / "b", {
        "name": "b", "version": "1.0.0", "entry_point": "plugin:B", "dependencies": ["a"],
    })

    loader = PluginLoader(tmp_path)
    with pytest.raises(CircularDependencyError):
        loader.discover_in_dependency_order()


def test_discover_method_itself_is_unaffected_by_v0_3_3_changes(tmp_path: Path):
    """Regression guard: discover() must still return raw, unordered
    results and must NOT raise on a missing dependency -- only
    discover_in_dependency_order() performs dependency validation."""
    _write_manifest(tmp_path / "weather", {
        "name": "weather",
        "version": "1.0.0",
        "entry_point": "plugin:WeatherPlugin",
        "dependencies": ["nonexistent_plugin"],
    })

    loader = PluginLoader(tmp_path)
    discovered = loader.discover()
    assert len(discovered) == 1
    assert discovered[0].name == "weather"


def test_discover_in_dependency_order_against_real_modules_directory():
    """End-to-end proof against the actual project modules/ directory:
    the real weather/ fixture has no dependencies, so this must resolve
    cleanly without raising."""
    project_root = Path(__file__).resolve().parents[2]
    modules_dir = project_root / "modules"

    loader = PluginLoader(modules_dir)
    ordered = loader.discover_in_dependency_order()

    names = {m.name for m in ordered}
    assert "weather" in names
