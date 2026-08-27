"""Version synchronization: patch ownership.toml memory_version across known projects.

Migrated from memory-core ``memory_core/tools/version_sync.py`` (M3).
Behaviour is kept equivalent; the adaptations are:

- Protocol constants ``CURRENT_MEMORY_VERSION`` and ``CANONICAL_MEMORY_LOCK_SCHEMA``
  are NOT imported from memory_core; they are passed in by callers as parameters
  (target_version and canonical_schema).
- Signing (resign) is NOT imported from memory_core; a module-level injection
  hook ``set_resign_hook(hook)`` allows callers to inject their own resign
  function. Default is a no-op that reports ``"resigned": False`` with reason
  ``"resign hook not injected"``.
- The global ``sync_all_known_projects`` is preserved; ``infra-cli version-sweep
  --all`` exposes it.
- ``probe_version_and_sync`` accepts ``current_version`` as a parameter so the
  caller can supply its own protocol constant.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resign hook injection
# ---------------------------------------------------------------------------

# Type for the resign hook:
#   (project_path, changed_paths) -> {"resigned": bool, "reason"|"paths": ...}
ResignHook = Callable[[Path, list[str]], dict[str, Any]]

_resign_hook: ResignHook | None = None


def _default_resign(project_path: Path, changed_paths: list[str]) -> dict[str, Any]:
    """Default resign hook: no-op, reports itself as not resigned."""
    return {
        "resigned": False,
        "reason": "resign hook not injected",
    }


def set_resign_hook(hook: ResignHook | None) -> None:
    """Inject (or clear) the resign hook.

    The hook is called after a successful three-file patch with the project
    path and the list of changed relative paths.  It must return a dict with
    at least ``"resigned": bool``.  On success include ``"paths": list[str]``.
    On failure include ``"reason": str``.

    Pass ``None`` to reset to the default no-op.
    """
    global _resign_hook  # noqa: PLW0603
    _resign_hook = hook


def get_resign_hook() -> ResignHook:
    """Return the currently injected resign hook, or the default no-op."""
    return _resign_hook if _resign_hook is not None else _default_resign


# ---------------------------------------------------------------------------
# Lock constants
# ---------------------------------------------------------------------------

# Stale lock threshold (seconds): a .sync.lock older than this is considered
# abandoned (e.g. process crashed while holding it) and is ignored/broken.
SYNC_LOCK_STALE_SECONDS = 10.0

# Lock acquisition retry budget (seconds): give concurrent holders a short
# window to finish instead of failing fast on the first EEXIST.
SYNC_LOCK_WAIT_SECONDS = 2.0


# ---------------------------------------------------------------------------
# Patch helpers (unchanged from memory-core original)
# ---------------------------------------------------------------------------


def read_ownership_memory_version(ownership_path: Path) -> str | None:
    """Read memory_version from an ownership.toml file.

    Returns None if file doesn't exist or field not found.
    """
    if not ownership_path.exists():
        return None
    try:
        content = ownership_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^memory_version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return match.group(1) if match else None


def patch_ownership_memory_version(ownership_path: Path, target_version: str) -> bool:
    """Patch memory_version in ownership.toml without rewriting the entire file.

    Returns True if patched, False if already up-to-date or skipped.
    M1: Atomic write with tmp + os.replace.
    """
    if not ownership_path.exists():
        return False
    try:
        content = ownership_path.read_text(encoding="utf-8")
    except OSError:
        return False

    new_content, count = re.subn(
        r'^(memory_version\s*=\s*)"[^"]+"',
        rf'\g<1>"{target_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0 or new_content == content:
        return False

    # Atomic write: tmp + os.replace
    tmp_path = ownership_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(new_content, encoding="utf-8")
        os.replace(tmp_path, ownership_path)  # noqa: PTH105
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return True


def patch_memory_lock(lock_path: Path, target_version: str) -> bool:
    """Patch memory_version and locked_at in memory.lock without rewriting.

    Returns True if patched, False if already up-to-date or skipped.
    M1: Atomic write with tmp + os.replace.
    """
    if not lock_path.exists():
        return False
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError:
        return False

    match = re.search(r'^memory_version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match and match.group(1) == target_version:
        return False

    new_content, count1 = re.subn(
        r'^(memory_version\s*=\s*)"[^"]+"',
        rf'\g<1>"{target_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count1 == 0:
        return False

    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    new_content, count2 = re.subn(
        r'^(locked_at\s*=\s*)"[^"]+"',
        rf'\g<1>"{now_iso}"',
        new_content,
        count=1,
        flags=re.MULTILINE,
    )
    if count2 == 0:
        return False

    tmp_path = lock_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(new_content, encoding="utf-8")
        os.replace(tmp_path, lock_path)  # noqa: PTH105
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return True


def patch_adapter_toml_version(adapter_path: Path, target_version: str) -> bool:
    """Patch version under [core] section in adapter.toml without rewriting.

    Returns True if patched, False if already up-to-date or skipped.
    M1: Atomic write with tmp + os.replace.
    """
    if not adapter_path.exists():
        return False
    try:
        content = adapter_path.read_text(encoding="utf-8")
    except OSError:
        return False

    lines = content.splitlines(keepends=True)
    in_core_section = False
    patched_lines: list[str] = []
    version_found = False
    version_already_correct = False

    for _i, line in enumerate(lines):
        if line.strip() == "[core]":
            in_core_section = True
            patched_lines.append(line)
            continue

        if in_core_section and line.strip().startswith("["):
            in_core_section = False

        if in_core_section and not version_found:
            match = re.match(r'^(version\s*=\s*)"([^"]+)"', line)
            if match:
                version_found = True
                if match.group(2) == target_version:
                    version_already_correct = True
                    patched_lines.append(line)
                else:
                    new_line = f'{match.group(1)}"{target_version}"\n'
                    patched_lines.append(new_line)
                continue

        patched_lines.append(line)

    if not version_found or version_already_correct:
        return False

    new_content = "".join(patched_lines)

    tmp_path = adapter_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(new_content, encoding="utf-8")
        os.replace(tmp_path, adapter_path)  # noqa: PTH105
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return True


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------


def _gate_version_bump(current_version: str, target_version: str, schema_changed: bool) -> str:
    """Gate check for version upgrade.

    Returns "allowed" if upgrade is safe (patch/minor + schema unchanged).
    Returns "blocked:<reason>" if upgrade requires migration or is a downgrade.
    """
    if schema_changed:
        return "blocked:schema_changed"

    try:
        from packaging.version import Version

        current = Version(current_version)
        target = Version(target_version)
    except Exception:
        if current_version == target_version:
            return "allowed"
        return "blocked:major"

    if target.major > current.major:
        return "blocked:major"

    if target < current:
        return "blocked:downgrade"

    return "allowed"


def _read_lock_schema_version(lock_path: Path) -> str | None:
    """Read schema_version from memory.lock file."""
    if not lock_path.exists():
        return None
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^schema_version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return match.group(1) if match else None


def _read_adapter_version(adapter_path: Path) -> str | None:  # noqa: ARG001
    """Read version from [core] section of adapter.toml."""
    if not adapter_path.exists():
        return None
    try:
        content = adapter_path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = content.splitlines()
    in_core = False
    for line in lines:
        if line.strip() == "[core]":
            in_core = True
            continue
        if in_core and line.strip().startswith("["):
            break
        if in_core:
            match = re.match(r'^version\s*=\s*"([^"]+)"', line)
            if match:
                return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Path-index (global mode)
# ---------------------------------------------------------------------------


def load_path_index(lifecycle_root: Path) -> dict[str, Any]:
    """Load path-index.json from the lifecycle root."""
    path = lifecycle_root / "project-lifecycle" / "path-index.json"
    if not path.exists():
        return {"paths": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"paths": {}}
    return data if isinstance(data, dict) else {"paths": {}}


# ---------------------------------------------------------------------------
# Concurrency lock (INFRA-545)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_lock(project_path: Path) -> Any:
    """Best-effort per-project concurrency guard for version sync (INFRA-545).

    Acquires ``memory/system/.sync.lock`` via ``O_CREAT|O_EXCL``.
    """
    lock_path = project_path / "memory" / "system" / ".sync.lock"
    owned = False
    deadline = time.monotonic() + SYNC_LOCK_WAIT_SECONDS

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > SYNC_LOCK_STALE_SECONDS:
                with contextlib.suppress(OSError):
                    lock_path.unlink()
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
            continue
        except OSError:
            break
        else:
            with contextlib.suppress(OSError):
                os.write(fd, f"{os.getpid()}".encode())
            os.close(fd)
            owned = True
            break

    try:
        yield owned
    finally:
        if owned:
            with contextlib.suppress(OSError):
                lock_path.unlink()


# ---------------------------------------------------------------------------
# Resign wrapper (uses the injected hook)
# ---------------------------------------------------------------------------


def _try_resign_all(project_path: Path, changed_paths: list[str]) -> dict[str, Any]:
    """Re-sign changed files after version patch using the injected hook.

    If no hook is injected, the default no-op returns
    ``{"resigned": False, "reason": "resign hook not injected"}``.
    """
    hook = get_resign_hook()
    try:
        return hook(project_path, changed_paths)
    except Exception as exc:
        return {"resigned": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Three-file patch under lock
# ---------------------------------------------------------------------------


def _patch_three_files_under_lock(
    project_path: Path,
    ownership_path: Path,
    lock_path: Path,
    adapter_path: Path,
    current_version: str,
    target_version: str,
) -> dict[str, Any]:
    """Run the three-file patch + resign critical section under .sync.lock."""
    result: dict[str, Any] = {"patched": False, "errors": []}

    with _sync_lock(project_path) as lock_acquired:
        if not lock_acquired:
            result["from"] = current_version
            result["to"] = target_version
            result["lock_skipped"] = True
            result["reason"] = "sync lock held by concurrent holder"
            return result

        locked_version = read_ownership_memory_version(ownership_path)
        if locked_version == target_version:
            result["reason"] = "already up-to-date"
            return result
        if locked_version is not None and locked_version != current_version:
            result["from"] = current_version
            result["to"] = locked_version
            result["reason"] = "version changed concurrently; skipping"
            return result

        changed_paths: list[str] = []

        try:
            if patch_ownership_memory_version(ownership_path, target_version):
                changed_paths.append("memory/system/ownership.toml")
        except OSError as exc:
            result["errors"].append({"step": "patch_ownership", "reason": str(exc)})

        try:
            if lock_path.exists() and patch_memory_lock(lock_path, target_version):
                changed_paths.append("memory/system/memory.lock")
        except OSError as exc:
            result["errors"].append({"step": "patch_lock", "reason": str(exc)})

        try:
            if adapter_path.exists() and patch_adapter_toml_version(adapter_path, target_version):
                changed_paths.append("memory/system/adapter.toml")
        except OSError as exc:
            result["errors"].append({"step": "patch_adapter", "reason": str(exc)})

        if changed_paths:
            result["patched"] = True
            result["from"] = current_version
            result["to"] = target_version
            result["files_changed"] = changed_paths

            resign_result = _try_resign_all(project_path, changed_paths)
            if not resign_result["resigned"]:
                result["errors"].append(
                    {
                        "step": "resign",
                        "reason": resign_result.get("reason", "unknown"),
                    }
                )
        else:
            result["reason"] = "no files changed"

    return result


# ---------------------------------------------------------------------------
# sync_single_project — parameterized (no memory_core constants)
# ---------------------------------------------------------------------------


def sync_single_project(
    project_path: Path,
    target_version: str,
    canonical_schema: str = "context-package-v1",
) -> dict[str, Any]:
    """Patch ownership.toml, memory.lock, and adapter.toml for a single project.

    Gate logic prevents automatic major/schema upgrades and downgrades.

    Args:
        project_path: Path to the project root.
        target_version: Target memory version (caller-supplied, not from
            any hardcoded constant).
        canonical_schema: The canonical schema_version string to compare
            against. Defaults to ``"context-package-v1"``.

    Returns a result dict with patched/blocked/errors.
    """
    result: dict[str, Any] = {"patched": False, "errors": []}

    ownership_path = project_path / "memory" / "system" / "ownership.toml"
    if not ownership_path.exists():
        result["reason"] = "no ownership.toml"
        return result

    current_version = read_ownership_memory_version(ownership_path)
    if current_version is None:
        result["reason"] = "cannot read memory_version from ownership.toml"
        return result

    if current_version == target_version:
        result["patched"] = False
        result["reason"] = "already up-to-date"
        return result

    lock_path = project_path / "memory" / "system" / "memory.lock"
    adapter_path = project_path / "memory" / "system" / "adapter.toml"

    current_schema = _read_lock_schema_version(lock_path)
    schema_changed = current_schema is not None and current_schema != canonical_schema

    gate_result = _gate_version_bump(current_version, target_version, schema_changed)

    if gate_result.startswith("blocked"):
        logging.warning(
            "Version sync blocked: %s (current=%s, target=%s)",
            gate_result,
            current_version,
            target_version,
        )
        result["patched"] = False
        result["from"] = current_version
        result["to"] = target_version
        result["gate_blocked"] = True
        result["gate_reason"] = gate_result
        result["reason"] = f"gate blocked: {gate_result}"
        return result

    return _patch_three_files_under_lock(
        project_path,
        ownership_path,
        lock_path,
        adapter_path,
        current_version,
        target_version,
    )


# ---------------------------------------------------------------------------
# sync_all_known_projects — parameterized
# ---------------------------------------------------------------------------


def sync_all_known_projects(
    lifecycle_root: Path | None = None,
    target_version: str | None = None,
    canonical_schema: str = "context-package-v1",
) -> dict[str, Any]:
    """Iterate all registered projects and patch three files if version is stale.

    Args:
        lifecycle_root: Root of the lifecycle directory. Defaults to
            ``~/.memory-core``.
        target_version: Target version string. **Required** — no implicit
            default from any protocol constant.
        canonical_schema: The canonical schema_version to compare against.

    Returns a report dict with patched/skipped/errors lists.
    """
    if target_version is None:
        return {
            "target_version": None,
            "patched": [],
            "skipped": [],
            "errors": [{"path": "", "name": "", "reason": "target_version is required"}],
        }

    if lifecycle_root is None:
        lifecycle_root = Path("~/.memory-core").expanduser()

    report: dict[str, Any] = {
        "target_version": target_version,
        "patched": [],
        "skipped": [],
        "errors": [],
    }

    path_index = load_path_index(lifecycle_root)
    paths = path_index.get("paths", {})
    if not isinstance(paths, dict):
        return report

    for local_path, entry in paths.items():
        if not isinstance(entry, dict):
            continue
        project_name = entry.get("project_name", "unknown")
        try:
            project_path = Path(local_path)
            ownership_path = project_path / "memory" / "system" / "ownership.toml"
            current_version = read_ownership_memory_version(ownership_path)
            if current_version is None:
                report["skipped"].append(
                    {
                        "path": local_path,
                        "name": project_name,
                        "reason": "no ownership.toml",
                    }
                )
                continue
            if current_version == target_version:
                report["skipped"].append(
                    {
                        "path": local_path,
                        "name": project_name,
                        "reason": "already up-to-date",
                    }
                )
                continue

            single_result = sync_single_project(project_path, target_version, canonical_schema)

            if single_result.get("patched"):
                entry_data = {
                    "path": local_path,
                    "name": project_name,
                    "from": current_version,
                    "to": target_version,
                }
                if single_result.get("gate_blocked"):
                    entry_data["gate_blocked"] = True
                    entry_data["gate_reason"] = single_result.get("gate_reason", "")
                if single_result.get("files_changed"):
                    entry_data["files_changed"] = single_result["files_changed"]
                report["patched"].append(entry_data)

            for error in single_result.get("errors", []):
                report["errors"].append(
                    {
                        "path": local_path,
                        "name": project_name,
                        **error,
                    }
                )
        except Exception as exc:
            report["errors"].append({"path": local_path, "name": project_name, "reason": str(exc)})

    return report


# ---------------------------------------------------------------------------
# probe_version_and_sync — parameterized (gateway session-start hot path)
# ---------------------------------------------------------------------------


def probe_version_and_sync(
    project_path: Path,
    current_version: str,
    canonical_schema: str = "context-package-v1",
) -> dict[str, Any] | None:
    """Gateway session-start probe: detect version mismatch and auto-sync.

    Fail-safe: any exception returns None, never blocks hook main chain.

    Args:
        project_path: Path to the consumer project root.
        current_version: The current memory-core protocol version to sync to.
            Caller-supplied — infra-core does not hardcode this.
        canonical_schema: Canonical schema version for gate check.
    """
    try:
        lock_path = project_path / "memory" / "system" / "memory.lock"
        if not lock_path.exists():
            return None

        try:
            content = lock_path.read_text(encoding="utf-8")
        except OSError:
            return None

        match = re.search(r'^memory_version\s*=\s*"([^"]+)"', content, re.MULTILINE)
        if not match:
            return None

        lock_version = match.group(1)
        if lock_version == current_version:
            return None

        return sync_single_project(project_path, current_version, canonical_schema)

    except Exception as exc:
        logger.debug("probe_version_and_sync failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI: sync ownership.toml memory_version across known projects."""
    parser = argparse.ArgumentParser(
        description="Sync ownership.toml memory_version across all known projects."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Sync a single project path instead of all known projects.",
    )
    parser.add_argument(
        "--target-version",
        type=str,
        required=True,
        help="Target version to sync to (required; not hardcoded).",
    )
    parser.add_argument(
        "--canonical-schema",
        type=str,
        default="context-package-v1",
        help="Canonical schema_version for gate check (default: context-package-v1).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_projects",
        help="Sync all known projects (global mode).",
    )
    parser.add_argument(
        "--lifecycle-root",
        type=Path,
        default=None,
        help="Lifecycle root directory (default: ~/.memory-core).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON.",
    )
    args = parser.parse_args(argv)

    if args.target:
        target = args.target.resolve()
        if not target.is_dir():
            print(f"Error: {target} is not a directory", file=sys.stderr)
            return 2
        result = sync_single_project(target, args.target_version, args.canonical_schema)
    elif args.all_projects:
        result = sync_all_known_projects(
            args.lifecycle_root, args.target_version, args.canonical_schema
        )
    else:
        # Default: single project at cwd
        result = sync_single_project(Path.cwd(), args.target_version, args.canonical_schema)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if "patched" in result and isinstance(result.get("patched"), list):
            for entry in result.get("patched", []):
                print(f"  [PATCH] {entry['name']}: {entry['from']} -> {entry['to']}")
            for entry in result.get("skipped", []):
                print(f"  [SKIP]  {entry['name']}: {entry['reason']}")
            for entry in result.get("errors", []):
                print(f"  [ERROR] {entry['name']}: {entry['reason']}")
        else:
            if result.get("patched"):
                print(f"Patched: {result['from']} -> {result['to']}")
            else:
                print(f"Skipped: {result.get('reason', 'unknown')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
