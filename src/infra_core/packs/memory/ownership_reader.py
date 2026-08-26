"""Default ownership classifier for the memory rule pack.

Reads a target project's ``memory/system/ownership.toml`` and provides
a minimal ``classify_owned_path`` implementation (~100 lines) that does
not depend on memory_core.ownership.

This is the default classifier injected into layout_audit.  memory-core
consumers may inject their own ``classify_owned_path`` (from
``memory_core.ownership``) for semantic parity; the anti-drift contract
test asserts both produce identical outputs on a shared JSON corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


@dataclass(frozen=True)
class OwnedDomain:
    """A domain of owned paths."""

    name: str
    path: str
    level: str  # "critical", "standard", "recommended"
    recursive: bool = True
    description: str = ""


@dataclass(frozen=True)
class Owned:
    """Classification result: path is owned/protected."""

    domain: OwnedDomain | None = None
    level: str = "standard"
    reason: str = ""


@dataclass(frozen=True)
class NotOwned:
    """Classification result: path is not owned."""

    reason: str = ""


ClassificationResult = Owned | NotOwned


@dataclass
class OwnershipConfig:
    """Parsed ownership configuration."""

    domains: list[OwnedDomain] = field(default_factory=list)


def load_ownership_toml(project_root: Path) -> OwnershipConfig:
    """Load ownership.toml from a project's memory/system/ directory.

    Returns an empty OwnershipConfig if the file does not exist.
    """
    ownership_path = project_root / "memory" / "system" / "ownership.toml"
    if not ownership_path.exists():
        return OwnershipConfig()

    try:
        with open(ownership_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return OwnershipConfig()

    domains: list[OwnedDomain] = []
    for d in data.get("domains", []):
        if not isinstance(d, dict):
            continue
        domains.append(
            OwnedDomain(
                name=str(d.get("name", "")),
                path=str(d.get("path", "")).replace("\\", "/").strip("/"),
                level=str(d.get("level", "standard")).lower(),
                recursive=bool(d.get("recursive", True)),
                description=str(d.get("description", "")),
            )
        )

    return OwnershipConfig(domains=domains)


def classify_owned_path(
    rel_path: str | Path,
    ownership: OwnershipConfig | None = None,
    project_root: Path | None = None,
) -> ClassificationResult:
    """Classify a path as owned or not-owned.

    Args:
        rel_path: Relative path from project root
        ownership: Ownership config (loaded from project_root if None)
        project_root: Project root for loading ownership.toml

    Returns:
        Owned if the path is under a declared domain, NotOwned otherwise.
    """
    path_str = str(rel_path).replace("\\", "/").strip("/")

    # Remove leading ./ or ../
    while path_str.startswith("./"):
        path_str = path_str[2:]

    if ownership is None:
        if project_root is None:
            return NotOwned(reason="No ownership config or project root provided")
        ownership = load_ownership_toml(project_root)

    if not ownership.domains:
        return NotOwned(reason="No ownership domains declared")

    for domain in ownership.domains:
        domain_parts = domain.path.split("/")
        path_parts = path_str.split("/")

        if (
            len(path_parts) >= len(domain_parts)
            and path_parts[: len(domain_parts)] == domain_parts
            and (domain.recursive or len(path_parts) == len(domain_parts))
        ):
            return Owned(
                domain=domain,
                level=domain.level,
                reason=f"Path under owned domain: {domain.name}",
            )

    return NotOwned(reason="Path not in any owned domain")
