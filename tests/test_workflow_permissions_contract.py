"""Workflow permissions contract tests (F4 — VAL-M2-104/105/107).

Two guard assertions:
1. Every workflow must have explicit permissions (top-level or full job-level
   coverage), never relying on GitHub's implicit defaults.
2. ci.yml and qa.yml triggers must never have paths/paths-ignore filters —
   ci-ok/qa-ok are required checks; paths filters would make them permanently
   pending, blocking the entire repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _load_workflow(name: str) -> dict:
    """Load a workflow YAML file."""
    path = WORKFLOWS_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not found")
    with open(path) as f:
        return yaml.safe_load(f)


def _all_workflow_names() -> list[str]:
    """List all workflow YAML files."""
    return sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml"))


def _workflow_has_top_level_permissions(wf: dict) -> bool:
    """Check if workflow has top-level permissions block."""
    return "permissions" in wf and wf["permissions"] is not None


def _workflow_has_full_job_coverage(wf: dict) -> bool:
    """Check if every job has its own permissions block."""
    jobs = wf.get("jobs", {})
    if not jobs:
        return True
    return all("permissions" in job for job in jobs.values())


def _workflow_has_explicit_permissions(wf: dict) -> bool:
    """A workflow is explicit if it has top-level permissions OR all jobs do."""
    return _workflow_has_top_level_permissions(wf) or _workflow_has_full_job_coverage(wf)


class TestWorkflowPermissionsExplicit:
    """VAL-M2-104: Every workflow must declare explicit permissions.

    No workflow may rely on GitHub's implicit default token permissions
    (which grant contents:write and other broad scopes).
    """

    @pytest.mark.parametrize("wf_name", _all_workflow_names())
    def test_workflow_has_explicit_permissions(self, wf_name: str) -> None:
        """Each workflow must have top-level or full job-level permissions."""
        wf = _load_workflow(wf_name)
        assert _workflow_has_explicit_permissions(wf), (
            f"{wf_name}: workflow has neither top-level 'permissions' nor "
            f"full job-level coverage — relies on implicit GITHUB_TOKEN defaults. "
            f"Add top-level 'permissions: {{contents: read}}' or per-job declarations."
        )


class TestRequiredCheckReachability:
    """VAL-M2-107: ci.yml/qa.yml triggers must never have paths filters.

    ci-ok and qa-ok are required checks. If their workflow triggers include
    paths or paths-ignore filters, the workflow may be skipped for certain PRs,
    leaving the required check permanently pending and blocking all merges.
    """

    @pytest.mark.parametrize(
        "wf_name",
        ["ci.yml", "qa.yml"],
    )
    def test_no_paths_filter_in_triggers(self, wf_name: str) -> None:
        """Trigger events must not include paths or paths-ignore filters."""
        wf = _load_workflow(wf_name)
        triggers = wf.get(True, {})  # yaml parses 'on:' as boolean True key
        if triggers is None:
            pytest.skip(f"{wf_name}: no triggers found")

        for event_name, event_config in triggers.items():
            if event_config is None:
                continue
            if not isinstance(event_config, dict):
                continue
            assert "paths" not in event_config, (
                f"{wf_name}: trigger '{event_name}' has 'paths' filter — "
                f"this would skip the workflow for some PRs, leaving the "
                f"required check (ci-ok/qa-ok) permanently pending. "
                f"Remove the paths filter."
            )
            assert "paths-ignore" not in event_config, (
                f"{wf_name}: trigger '{event_name}' has 'paths-ignore' filter — "
                f"this would skip the workflow for some PRs, leaving the "
                f"required check (ci-ok/qa-ok) permanently pending. "
                f"Remove the paths-ignore filter."
            )


class TestNoIdTokenWrite:
    """VAL-M2-103: id-token: write must be removed after OIDC audit.

    The review-shard jobs in droid-review.yml and droid-review-shards.yml
    had id-token: write but no OIDC usage. Audit confirmed no OIDC dependency
    (no cloud credential exchange, no actions-oidc steps).
    """

    @pytest.mark.parametrize(
        "wf_name",
        ["droid-review.yml", "droid-review-shards.yml"],
    )
    def test_no_id_token_write(self, wf_name: str) -> None:
        """No job in these workflows should have id-token: write."""
        wf = _load_workflow(wf_name)
        jobs = wf.get("jobs", {})
        for job_name, job_config in jobs.items():
            perms = job_config.get("permissions", {})
            if perms and perms.get("id-token") == "write":
                pytest.fail(
                    f"{wf_name}: job '{job_name}' has 'id-token: write' — "
                    f"OIDC audit confirmed no dependency. Remove it."
                )

    def test_no_id_token_write_in_any_workflow(self) -> None:
        """No workflow in the repo should have id-token: write."""
        for wf_name in _all_workflow_names():
            wf = _load_workflow(wf_name)
            # Check top-level
            top_perms = wf.get("permissions", {})
            if isinstance(top_perms, dict) and top_perms.get("id-token") == "write":
                pytest.fail(f"{wf_name}: top-level has id-token: write")
            # Check job-level
            jobs = wf.get("jobs", {})
            for job_name, job_config in jobs.items():
                perms = job_config.get("permissions", {})
                if isinstance(perms, dict) and perms.get("id-token") == "write":
                    pytest.fail(f"{wf_name}: job '{job_name}' has id-token: write")
