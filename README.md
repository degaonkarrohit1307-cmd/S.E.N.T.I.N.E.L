# S.E.N.T.I.N.E.L. — v0.3.3 Plugin Dependency Resolution

This is the current state of the project, built incrementally per the
roadmap in the master SAD (Part 10): **Core Engine, Event Bus, Module
Registry, Security Manager, Configuration Manager, and a Plugin system
with discovery, lifecycle management, and dependency resolution.**

## What's actually working right now
- An async, priority-laned Event Bus (critical/high/normal), with a
  per-handler circuit breaker so one broken handler can't take down the
  bus.
- A Module Registry that loads a `module.manifest.json`, validates
  dependencies, and registers each module's declared permission scopes
  with the Security Manager *before* the module ever runs.
- A Security Manager that enforces "declared in manifest **and** granted
  by the user" before authorizing any scope, and writes every decision
  (granted or denied) to an append-only audit log.
- One real demo module (`demo_echo`) proving the Module Registry chain
  end to end.
- A Configuration Manager: JSON/YAML/env-var sources, precedence
  merging, schema validation, runtime overrides, and a hot-reload hook.
- A Plugin system, separate from the Module Registry, built in three
  stages:
  - **Discovery** (`PluginLoader`) — recursively finds every
    `manifest.json` under `modules/`, coexisting with the Module
    Registry's `module.manifest.json` files with zero collision.
  - **Lifecycle** (`PluginLifecycleManager`) — enforces the
    `DISCOVERED → LOADED → INITIALIZED → RUNNING → STOPPED → UNLOADED`
    state machine, invoking each plugin's optional lifecycle hooks.
  - **Dependency resolution** (`DependencyGraph` + `DependencyResolver`)
    — validates a plugin's declared `dependencies` and computes a safe
    load order via Kahn's Algorithm, rejecting missing dependencies,
    duplicate plugin names, self-dependencies, and circular chains.
- One real demo plugin (`weather`) proving the discovery pipeline
  end to end against the actual `modules/` directory.

## What's deliberately NOT here yet
- Voice, Vision, PC Controller, Android Bridge, Memory Engine — all
  later versions (see the master SAD, Part 10).
- Biometric authentication or interactive confirmation prompts (v0.7).
- Hot-reload / side-by-side module versioning for the Module Registry
  (deferred to v0.2+). Config hot-reload is designed but not wired to a
  file-watcher (v0.2 ADR-0003).
- Dynamic import of plugin entry points, and a `PluginManager` tying
  discovery + dependency order + lifecycle together into one
  orchestrated startup flow (both are the next natural phase — see
  ADR-0006's "Future extension points").

## Run it
```bash
pip install -r requirements.txt
python main.py
```
Expected output: an echoed reply event, the audit log path, and the
active `event_bus.queue_size` (proving config was loaded).

Try an override:
```bash
SENTINEL_EVENT_BUS__QUEUE_SIZE=42 python main.py
```
The printed queue size changes from `1000` to `42` — env vars win over
`core/config/default.json`.

## Test it
```bash
pytest tests/unit/ -v
```
110 tests total:
- 8 for the kernel/event-bus/security foundation (v0.1/v0.1.1)
- 19 for the Configuration Manager (v0.2)
- 23 for Plugin Discovery (v0.3.1)
- 25 for Plugin Lifecycle Management (v0.3.2)
- 35 for Plugin Dependency Resolution (v0.3.3)

## Folder map
```
core/                  Kernel, Event Bus, Module Registry, Config Manager, config files
core/plugin_loader/     PluginLoader, PluginLifecycleManager, DependencyGraph,
                        DependencyResolver, and plugin-system exceptions
domain/                Framework-free entities (Event, ModuleManifest, ConfigSchema,
                        PluginState, PluginDependency) and ports — Clean
                        Architecture's innermost layer
modules/
  security_manager/     The security module itself (Module Registry)
  demo_echo/            Minimal module proving the Module Registry pipeline works
  weather/              Minimal plugin proving the Plugin discovery pipeline works
tests/unit/            pytest suite
docs/adr/              Architecture Decision Records
```

## Version history
- **v0.1.0** — Core Kernel, Event Bus, Module Registry, Security Manager
  skeleton, demo_echo, 7 tests.
- **v0.1.1** — Review-only patch: fixed invocation-dependent import
  failure, an `id(handler)` reuse hazard in the circuit breaker, and a
  dead-letter duplication bug. 8 tests, no API changes. See
  `docs/adr/0002-v0.1.1-review-fixes.md`.
- **v0.2.0** — Configuration Manager: JSON/YAML/env loading, precedence
  merging, schema validation, type-safe access, runtime overrides,
  hot-reload hook. Integrated into Kernel and Event Bus via new optional
  parameters (zero breaking changes). 27 tests. See
  `docs/adr/0003-v0.2-configuration-manager.md`.
- **v0.3.1** — Plugin Discovery: recursive scan for `manifest.json`,
  strongly-typed `PluginManifest`, graceful skip of invalid manifests.
  Coexists with the Module Registry by filename alone. 50 tests. See
  `docs/adr/0004-v0.3-phase1-plugin-discovery.md`.
- **v0.3.2** — Plugin Lifecycle Management: `PluginState` state machine,
  `PluginLifecycleManager` enforcing valid transitions and invoking
  optional lifecycle hooks gracefully. 75 tests, 100% coverage on new
  modules. See `docs/adr/0005-v0.3.2-plugin-lifecycle.md`.
- **v0.3.3** — Plugin Dependency Resolution: `DependencyGraph` (directed
  graph of plugin dependencies) and `DependencyResolver` (Kahn's
  Algorithm topological sort), integrated into `PluginLoader` via a new
  `discover_in_dependency_order()` method. 110 tests, 99% coverage on
  new modules. See `docs/adr/0006-v0.3.3-plugin-dependency-resolution.md`.

## Next up (not yet scoped, awaiting approval)
Candidates per ADR-0006: dynamic import of plugin entry points, and a
`PluginManager` orchestrating discovery → dependency order → lifecycle
as one coherent startup flow.
