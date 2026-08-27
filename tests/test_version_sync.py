"""Tests for migrated version_sync module (M3).

Covers:
- VAL-SEAM-002: Default resign hook is no-op, reports resigned:false
- VAL-SEAM-003: Injected resign hook produces real re-sign
- VAL-SEAM-006: Protocol constants not hardcoded, caller-supplied
- Behavior equivalence with memory-core original
- Resign hook injection mechanism
- Gate logic, lock, three-file patch
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from infra_core.engine.version_sync import (
    _default_resign,
    _gate_version_bump,
    _try_resign_all,
    get_resign_hook,
    patch_adapter_toml_version,
    patch_memory_lock,
    patch_ownership_memory_version,
    probe_version_and_sync,
    read_ownership_memory_version,
    set_resign_hook,
    sync_all_known_projects,
    sync_single_project,
)

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, version: str = "0.9.0") -> Path:
    """Create a minimal project fixture."""
    project = tmp_path / "test-project"
    (project / "memory" / "system").mkdir(parents=True)

    ownership = project / "memory" / "system" / "ownership.toml"
    ownership.write_text(
        f'[project]\nname = "test"\nmemory_version = "{version}"\n',
        encoding="utf-8",
    )

    lock = project / "memory" / "system" / "memory.lock"
    lock.write_text(
        f'memory_version = "{version}"\n'
        f'schema_version = "context-package-v1"\n'
        f'adapter_version = "builtin"\n'
        f'lock_reason = "memory-init"\n'
        f'locked_at = "2026-01-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    adapter = project / "memory" / "system" / "adapter.toml"
    adapter.write_text(
        f'[core]\nversion = "{version}"\nmemory_dir = "memory"\n',
        encoding="utf-8",
    )

    return project


# ---------------------------------------------------------------------------
# VAL-SEAM-002: Default resign hook is no-op
# ---------------------------------------------------------------------------


class TestDefaultResignHook:
    """Default resign hook returns resigned:false with reason."""

    def test_default_resign_returns_false(self, tmp_path: Path) -> None:
        """Default resign hook returns resigned:false."""
        result = _default_resign(tmp_path, ["file1", "file2"])
        assert result["resigned"] is False
        assert "resign hook not injected" in result["reason"]

    def test_sync_without_injected_hook_reports_not_resigned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sync_single_project without injected hook reports resigned:false."""
        set_resign_hook(None)  # Reset to default

        project = _make_project(tmp_path, "0.9.0")
        result = sync_single_project(project, "0.9.1")

        assert result["patched"] is True
        assert len(result["errors"]) > 0
        resign_error = next((e for e in result["errors"] if e.get("step") == "resign"), None)
        assert resign_error is not None
        assert "resign hook not injected" in resign_error["reason"]

    def test_get_resign_hook_returns_default_when_none_injected(self) -> None:
        """get_resign_hook returns default when nothing injected."""
        set_resign_hook(None)
        hook = get_resign_hook()
        assert hook == _default_resign


# ---------------------------------------------------------------------------
# VAL-SEAM-003: Injected resign hook produces real re-sign
# ---------------------------------------------------------------------------


class TestInjectedResignHook:
    """Injected resign hook is called and produces real re-sign."""

    def test_injected_hook_is_called(self, tmp_path: Path) -> None:
        """Injected resign hook is called with correct arguments."""
        mock_hook = MagicMock(return_value={"resigned": True, "paths": ["file1"]})
        set_resign_hook(mock_hook)

        project = _make_project(tmp_path, "0.9.0")
        result = sync_single_project(project, "0.9.1")

        assert result["patched"] is True
        assert len(result["errors"]) == 0  # No resign error
        mock_hook.assert_called_once()
        call_args = mock_hook.call_args[0]
        assert call_args[0] == project
        assert "memory/system/ownership.toml" in call_args[1]

        set_resign_hook(None)  # Cleanup

    def test_injected_hook_with_memory_core_wrapper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Injected hook wrapping memory-core's load_key+sign works."""

        # Simulate memory-core's resign wrapper
        def memory_core_resign_wrapper(project_path: Path, changed_paths: list[str]) -> dict:
            # Simulate: load key, sign, return success
            return {"resigned": True, "paths": changed_paths}

        set_resign_hook(memory_core_resign_wrapper)

        project = _make_project(tmp_path, "0.9.0")
        result = sync_single_project(project, "0.9.1")

        assert result["patched"] is True
        assert len(result["errors"]) == 0

        set_resign_hook(None)  # Cleanup

    def test_injected_hook_failure_recorded_in_errors(self, tmp_path: Path) -> None:
        """Injected hook failure is recorded in errors."""
        mock_hook = MagicMock(return_value={"resigned": False, "reason": "signing failed"})
        set_resign_hook(mock_hook)

        project = _make_project(tmp_path, "0.9.0")
        result = sync_single_project(project, "0.9.1")

        assert result["patched"] is True
        resign_error = next((e for e in result["errors"] if e.get("step") == "resign"), None)
        assert resign_error is not None
        assert "signing failed" in resign_error["reason"]

        set_resign_hook(None)  # Cleanup


# ---------------------------------------------------------------------------
# VAL-SEAM-006: Protocol constants not hardcoded
# ---------------------------------------------------------------------------


class TestProtocolConstantsParameterized:
    """Protocol constants are caller-supplied, not hardcoded."""

    def test_target_version_is_parameter(self, tmp_path: Path) -> None:
        """target_version is a parameter, not from a constant."""
        set_resign_hook(None)

        project = _make_project(tmp_path, "0.9.0")
        # Pass arbitrary version (use patch-level to avoid gate blocking)
        result = sync_single_project(project, "0.9.5")

        assert result["patched"] is True
        ownership = (project / "memory" / "system" / "ownership.toml").read_text()
        assert 'memory_version = "0.9.5"' in ownership

    def test_canonical_schema_is_parameter(self, tmp_path: Path) -> None:
        """canonical_schema is a parameter, not from a constant."""
        set_resign_hook(None)

        project = tmp_path / "test-project"
        (project / "memory" / "system").mkdir(parents=True)

        ownership = project / "memory" / "system" / "ownership.toml"
        ownership.write_text(
            '[project]\nname = "test"\nmemory_version = "0.9.0"\n',
            encoding="utf-8",
        )

        lock = project / "memory" / "system" / "memory.lock"
        lock.write_text(
            'memory_version = "0.9.0"\n'
            'schema_version = "custom-schema-v2"\n'
            'locked_at = "2026-01-01T00:00:00+00:00"\n',
            encoding="utf-8",
        )

        adapter = project / "memory" / "system" / "adapter.toml"
        adapter.write_text(
            '[core]\nversion = "0.9.0"\n',
            encoding="utf-8",
        )

        # Pass matching canonical schema
        result = sync_single_project(project, "0.9.1", "custom-schema-v2")

        assert result["patched"] is True
        assert result.get("gate_blocked") is not True

    def test_probe_version_and_sync_parameterized(self, tmp_path: Path) -> None:
        """probe_version_and_sync accepts current_version as parameter."""
        set_resign_hook(None)

        project = _make_project(tmp_path, "0.9.0")
        result = probe_version_and_sync(project, "0.9.1")

        assert result is not None
        assert result["patched"] is True

    def test_sync_all_known_projects_requires_target_version(self, tmp_path: Path) -> None:
        """sync_all_known_projects requires target_version parameter."""
        result = sync_all_known_projects(lifecycle_root=tmp_path, target_version=None)

        assert len(result["errors"]) > 0
        assert "target_version is required" in result["errors"][0]["reason"]


# ---------------------------------------------------------------------------
# Behavior equivalence with memory-core original
# ---------------------------------------------------------------------------


class TestBehaviorEquivalence:
    """Behavior matches memory-core original."""

    def test_patch_ownership_memory_version(self, tmp_path: Path) -> None:
        """patch_ownership_memory_version works as original."""
        ownership = tmp_path / "ownership.toml"
        ownership.write_text(
            '[project]\nname = "test"\nmemory_version = "0.9.0"\n',
            encoding="utf-8",
        )

        result = patch_ownership_memory_version(ownership, "0.9.1")
        assert result is True

        content = ownership.read_text()
        assert 'memory_version = "0.9.1"' in content

    def test_patch_memory_lock(self, tmp_path: Path) -> None:
        """patch_memory_lock works as original."""
        lock = tmp_path / "memory.lock"
        lock.write_text(
            'memory_version = "0.9.0"\nlocked_at = "2026-01-01T00:00:00+00:00"\n',
            encoding="utf-8",
        )

        result = patch_memory_lock(lock, "0.9.1")
        assert result is True

        content = lock.read_text()
        assert 'memory_version = "0.9.1"' in content
        assert "2026-01-01T00:00:00+00:00" not in content

    def test_patch_adapter_toml_version(self, tmp_path: Path) -> None:
        """patch_adapter_toml_version works as original."""
        adapter = tmp_path / "adapter.toml"
        adapter.write_text(
            '[core]\nversion = "0.9.0"\n',
            encoding="utf-8",
        )

        result = patch_adapter_toml_version(adapter, "0.9.1")
        assert result is True

        content = adapter.read_text()
        assert 'version = "0.9.1"' in content

    def test_read_ownership_memory_version(self, tmp_path: Path) -> None:
        """read_ownership_memory_version works as original."""
        ownership = tmp_path / "ownership.toml"
        ownership.write_text(
            '[project]\nname = "test"\nmemory_version = "0.9.5"\n',
            encoding="utf-8",
        )

        result = read_ownership_memory_version(ownership)
        assert result == "0.9.5"

    def test_gate_version_bump(self) -> None:
        """_gate_version_bump logic unchanged."""
        assert _gate_version_bump("0.10.2", "0.10.3", False) == "allowed"
        assert _gate_version_bump("0.10.2", "0.11.0", False) == "allowed"
        assert _gate_version_bump("0.10.2", "1.0.0", False) == "blocked:major"
        assert _gate_version_bump("0.10.2", "0.10.3", True) == "blocked:schema_changed"


# ---------------------------------------------------------------------------
# Resign hook injection mechanism
# ---------------------------------------------------------------------------


class TestResignHookMechanism:
    """Resign hook injection mechanism works correctly."""

    def test_set_and_get_resign_hook(self) -> None:
        """set_resign_hook and get_resign_hook work."""
        mock_hook = MagicMock()
        set_resign_hook(mock_hook)
        assert get_resign_hook() == mock_hook

        set_resign_hook(None)
        assert get_resign_hook() == _default_resign

    def test_try_resign_all_uses_injected_hook(self, tmp_path: Path) -> None:
        """_try_resign_all uses the injected hook."""
        mock_hook = MagicMock(return_value={"resigned": True, "paths": ["f1"]})
        set_resign_hook(mock_hook)

        result = _try_resign_all(tmp_path, ["f1", "f2"])

        assert result["resigned"] is True
        mock_hook.assert_called_once_with(tmp_path, ["f1", "f2"])

        set_resign_hook(None)  # Cleanup

    def test_try_resign_all_handles_hook_exception(self, tmp_path: Path) -> None:
        """_try_resign_all handles hook exceptions gracefully."""

        def failing_hook(project_path: Path, changed_paths: list[str]) -> dict:
            raise RuntimeError("signing error")

        set_resign_hook(failing_hook)

        result = _try_resign_all(tmp_path, ["f1"])

        assert result["resigned"] is False
        assert "signing error" in result["reason"]

        set_resign_hook(None)  # Cleanup
