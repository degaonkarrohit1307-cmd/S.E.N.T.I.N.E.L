"""
SecurityManager (v0.1 skeleton)

Scope covered in this version, per roadmap (SAD Part 10, v0.1):
  - modules must declare required scopes up front
  - authorize() only ever returns True for a (module, scope) pair that
    was BOTH declared by the module AND explicitly granted by the user
    in config/granted_scopes.yaml
  - every authorization decision is written to an append-only audit log

NOT in this version (arrives in v0.7, SAD Part 6.1):
  - voice/face biometric authentication
  - per-action interactive confirmation prompts

Building the enforcement POINT now, correctly, means nothing downstream
has to be rewired when richer auth is added later -- they'll just find
authorize() suddenly harder to satisfy, not differently shaped.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from domain.ports.system_ports import SecurityPort

logger = logging.getLogger("sentinel.security")


@dataclass
class AuditEntry:
    timestamp: str
    module_id: str
    scope: str
    granted: bool
    reason: str

    def to_dict(self) -> dict:
        return self.__dict__


class SecurityManager(SecurityPort):
    def __init__(self, granted_scopes_path: Path, audit_log_path: Path) -> None:
        self._granted_scopes_path = granted_scopes_path
        self._audit_log_path = audit_log_path
        self._declared_scopes: dict[str, tuple[str, ...]] = {}
        self._granted_scopes: dict[str, set[str]] = {}
        self._load_granted_scopes()
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    # -- SecurityPort -----------------------------------------------------

    def register_module_scopes(self, module_id: str, declared_scopes: tuple[str, ...]) -> None:
        self._declared_scopes[module_id] = declared_scopes
        logger.info("module %s declared scopes: %s", module_id, declared_scopes)

    def authorize(self, module_id: str, scope: str) -> bool:
        declared = self._declared_scopes.get(module_id, ())
        if scope not in declared:
            self.audit(module_id, scope, granted=False,
                       reason="scope not declared in manifest")
            return False

        granted = scope in self._granted_scopes.get(module_id, set())
        if not granted:
            self.audit(module_id, scope, granted=False,
                       reason="scope not granted by user")
            return False

        self.audit(module_id, scope, granted=True, reason="declared + granted")
        return True

    def audit(self, module_id: str, scope: str, granted: bool, reason: str = "") -> None:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            module_id=module_id,
            scope=scope,
            granted=granted,
            reason=reason,
        )
        with self._audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict()) + "\n")

    # -- internals ----------------------------------------------------------

    def _load_granted_scopes(self) -> None:
        """
        v0.1 keeps this deliberately simple: a flat JSON file the user
        edits by hand, of the shape:
            { "voice_engine": ["pc.process.launch"], ... }
        A proper Settings UI for granting/revoking scopes arrives with
        the desktop app in v0.6.
        """
        if not self._granted_scopes_path.exists():
            self._granted_scopes = {}
            return
        data = json.loads(self._granted_scopes_path.read_text(encoding="utf-8"))
        self._granted_scopes = {k: set(v) for k, v in data.items()}
