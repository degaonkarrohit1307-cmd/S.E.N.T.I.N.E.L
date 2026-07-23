"""
Domain entities: ModuleManifest, PermissionScope

A module declares what it is, what it needs, and what it can do, entirely
up front (SAD Part 4.2). The registry and security manager both validate
against this before a single line of the module's code runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "SemVer":
        major, minor, patch = (int(part) for part in text.split("."))
        return cls(major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ModuleManifest:
    """
    Mirrors module.manifest.json (SAD Part 4.2). Loaded and validated by
    the Module Registry before a module is instantiated.
    """
    id: str
    version: SemVer
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    required_scopes: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleManifest":
        return cls(
            id=data["id"],
            version=SemVer.parse(data["version"]),
            capabilities=tuple(data.get("capabilities", [])),
            required_scopes=tuple(data.get("required_scopes", [])),
            dependencies=tuple(data.get("dependencies", [])),
        )
