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
pip install pytest pytest-asyncio
python main.py
```
Expected output: an echoed reply event, plus a line confirming the audit
log was written to `core/config/audit.log`.

## Test it
```bash
pytest tests/unit/ -v
```
7 tests covering: event delivery, circuit-breaker tripping, priority-lane
isolation, and all three security authorization paths (undeclared scope
denied, declared-but-ungranted denied, declared-and-granted allowed).

## Folder map
```
core/            Kernel, Event Bus, Module Registry, config
domain/          Framework-free entities (Event, ModuleManifest) and
                 ports (interfaces) — Clean Architecture's innermost layer
modules/
  security_manager/   The security module itself
  demo_echo/           Minimal module proving the pipeline works
tests/unit/      pytest suite
docs/adr/        Architecture Decision Records
```

## Next up (v0.2, per the roadmap)
Memory Engine (episodic + profile, SQLite) and a CLI-based interaction
mode — still no voice yet, per the "narrow useful slice first" principle
in the master SAD's design philosophy.

# S.E.N.T.I.N.E.L.

Smart Executive Neural Technology for Intelligent Navigation, Evaluation & Learning

## Overview

S.E.N.T.I.N.E.L. is a modular AI Operating System designed as a long-term engineering project.

## Current Version

v0.1.0 – Kernel Foundation

## Features

- Modular Kernel
- Event Bus
- Security Manager
- Module Registry
- Audit Logging
- Unit Tests

## Roadmap

- v0.2 Configuration Manager
- v0.3 Plugin Loader
- v0.4 Memory Engine
- v0.5 Voice Interface
- ...
