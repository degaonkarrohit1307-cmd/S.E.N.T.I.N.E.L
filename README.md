# S.E.N.T.I.N.E.L. — v0.1 Kernel Foundation

This is the first runnable slice of the project, per the roadmap in the
master SAD (Part 10): **Core Engine, Event Bus, Module Registry, and a
Security Manager skeleton.**

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
- One real demo module (`demo_echo`) proving the whole chain end to end.

## What's deliberately NOT here yet
- Voice, Vision, PC Controller, Android Bridge, Memory Engine — all
  later versions (see `docs/adr/0001-v0.1-kernel-foundation.md` and the
  master SAD, Part 10).
- Biometric authentication or interactive confirmation prompts (v0.7).
- Hot-reload / side-by-side module versioning (deferred to v0.2+).

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
27 tests: 8 for the kernel/event-bus/security foundation (v0.1/v0.1.1),
19 for the Configuration Manager (v0.2) covering JSON/YAML loading,
missing/invalid files, defaults, env-var precedence, runtime overrides,
schema validation, and Kernel integration.

## Folder map
```
core/            Kernel, Event Bus, Module Registry, Config Manager, config files
domain/          Framework-free entities (Event, ModuleManifest, ConfigSchema)
                 and ports (interfaces) — Clean Architecture's innermost layer
modules/
  security_manager/   The security module itself
  demo_echo/           Minimal module proving the pipeline works
tests/unit/      pytest suite
docs/adr/        Architecture Decision Records
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

## Next up (v0.3, awaiting approval)
Not yet scoped — per project workflow, stopping here for review.
