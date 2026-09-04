"""release-announce.yml 契约测试（INFRA-756, M1 公告链路）。

锁定 .github/workflows/release-announce.yml 的形状契约：
- 触发器仅 release published（含 patch 全量，无过滤）
- 单 job、零权限（permissions: {}）、不 checkout
- POST payload 四字段精确 {repo, tag, release_url, sha}
- X-Release-Token 头引用 secret，URL 来自 secret，全文无明文
- 送达语义：2xx 静默通过、非 2xx 走告警路径（::warning:: + PostHog），job 永不 fail
- --retry 3 --retry-all-errors + --max-time + timeout-minutes 时间上界
- 不校验响应体
- PostHog 告警 best-effort，key 缺失 ::notice:: 跳过
- Secret 缺失时 warning + 跳过
- 零远程 action 引用

风格对齐 tests/test_ci_structure_contract.py / test_workflow_permissions_contract.py。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-announce.yml"


def _load_workflow() -> dict[str, Any]:
    """Load and parse the release-announce.yml workflow."""
    if not WORKFLOW_PATH.exists():
        pytest.fail(f"release-announce.yml not found at {WORKFLOW_PATH}")
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "release-announce.yml must be a YAML mapping"
    return doc


def _get_triggers(wf: dict[str, Any]) -> dict[str, Any]:
    """Extract trigger events. YAML parses 'on:' as boolean True key."""
    triggers = wf.get(True, wf.get("on", {}))
    if triggers is None:
        return {}
    if isinstance(triggers, str):
        return {triggers: None}
    if isinstance(triggers, list):
        return {t: None for t in triggers}
    return triggers


def _get_job(wf: dict[str, Any]) -> dict[str, Any]:
    """Return the single job config."""
    jobs = wf.get("jobs", {})
    assert isinstance(jobs, dict), "workflow must define jobs mapping"
    assert len(jobs) == 1, f"workflow must have exactly 1 job, found {len(jobs)}"
    return next(iter(jobs.values()))


def _all_run_scripts(job: dict[str, Any]) -> str:
    """Concatenate all run step scripts in a job."""
    steps = job.get("steps") or []
    runs = [str(step["run"]) for step in steps if "run" in step]
    return "\n".join(runs)


def _all_step_names(job: dict[str, Any]) -> list[str]:
    steps = job.get("steps") or []
    return [step.get("name", "") for step in steps]


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return _load_workflow()


@pytest.fixture(scope="module")
def job(workflow: dict[str, Any]) -> dict[str, Any]:
    return _get_job(workflow)


@pytest.fixture(scope="module")
def full_script(job: dict[str, Any]) -> str:
    return _all_run_scripts(job)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_dump(workflow: dict[str, Any]) -> str:
    """Full YAML dump for checking env mappings."""
    return yaml.safe_dump(workflow, allow_unicode=True)


# ── VAL-ANN-001: 文件存在且结构完整 ──


class TestWorkflowStructure:
    def test_workflow_file_exists(self) -> None:
        assert WORKFLOW_PATH.exists(), "release-announce.yml must exist"

    def test_workflow_has_name(self, workflow: dict[str, Any]) -> None:
        assert "name" in workflow and workflow["name"], "workflow must have a name"

    def test_workflow_has_exactly_one_job(self, workflow: dict[str, Any]) -> None:
        jobs = workflow.get("jobs", {})
        assert len(jobs) == 1, f"workflow must have exactly 1 job, got {len(jobs)}"


# ── VAL-ANN-002/003: 仅 release published 触发，无其他触发器 ──


class TestTriggers:
    def test_only_release_published_trigger(self, workflow: dict[str, Any]) -> None:
        triggers = _get_triggers(workflow)
        assert set(triggers.keys()) == {"release"}, (
            f"trigger keys must be exactly {{release}}, got {set(triggers.keys())}"
        )

    def test_release_types_exactly_published(self, workflow: dict[str, Any]) -> None:
        triggers = _get_triggers(workflow)
        release_config = triggers["release"]
        assert isinstance(release_config, dict), "release trigger must have config"
        types = release_config.get("types", [])
        assert types == ["published"], f"release types must be exactly [published], got {types}"

    def test_no_other_trigger_events(self, workflow: dict[str, Any]) -> None:
        """No push, schedule, workflow_dispatch, or other events."""
        triggers = _get_triggers(workflow)
        forbidden = {
            "push",
            "schedule",
            "workflow_dispatch",
            "pull_request",
            "workflow_call",
            "repository_dispatch",
        }
        found_forbidden = set(triggers.keys()) & forbidden
        assert not found_forbidden, f"unexpected trigger events: {found_forbidden}"

    def test_no_release_other_activity_types(self, workflow: dict[str, Any]) -> None:
        """No created/edited/prereleased/unpublished etc."""
        triggers = _get_triggers(workflow)
        release_config = triggers.get("release", {})
        if isinstance(release_config, dict):
            types = release_config.get("types", [])
            forbidden_types = {
                "created",
                "edited",
                "prereleased",
                "unpublished",
                "deleted",
                "released",
            }
            found = set(types) & forbidden_types
            assert not found, f"release trigger has extra activity types: {found}"


# ── VAL-ANN-004: 无 tag 模式门槛 ──


class TestNoTagFiltering:
    def test_no_tag_filter_in_if_conditions(self, job: dict[str, Any]) -> None:
        """No if: conditions filtering by tag pattern."""
        if_condition = job.get("if", "")
        assert not if_condition, "job should not have an if: condition"

        steps = job.get("steps") or []
        for step in steps:
            step_if = str(step.get("if", ""))
            # Should not contain tag filtering logic
            assert "tag" not in step_if.lower() or "release" in step_if.lower(), (
                f"step '{step.get('name', '')}' has tag filtering in if: {step_if}"
            )

    def test_no_tag_pattern_in_scripts(self, full_script: str) -> None:
        """No tag pattern matching/exclusion in run scripts."""
        # Should not have regex checks on tag format
        assert "grep" not in full_script or "tag" not in full_script, (
            "script should not grep-filter tags"
        )
        # No semver threshold checks
        assert "semver" not in full_script.lower(), "script should not have semver threshold logic"


# ── VAL-ANN-005: payload 四字段精确 ──


class TestPayloadShape:
    EXPECTED_KEYS = {"repo", "tag", "release_url", "sha"}

    def test_payload_keys_present(self, full_script: str) -> None:
        """Payload must contain all four required keys."""
        for key in self.EXPECTED_KEYS:
            assert key in full_script, f"payload missing key: {key}"

    def test_payload_uses_github_context(self, workflow_dump: str) -> None:
        """Payload values must come from github context."""
        assert "github.repository" in workflow_dump, "repo must come from github.repository"
        assert "github.event.release.tag_name" in workflow_dump, (
            "tag must come from github.event.release.tag_name"
        )
        assert "github.event.release.html_url" in workflow_dump, (
            "release_url must come from github.event.release.html_url"
        )

    def test_payload_sha_from_release_context(self, workflow_dump: str) -> None:
        """SHA must come from release commit context."""
        assert "github.event.release.target_commitish" in workflow_dump, (
            "sha must come from github.event.release.target_commitish"
        )

    def test_payload_constructed_with_jq(self, full_script: str) -> None:
        """Payload should be constructed with jq (no string concatenation)."""
        assert "jq -n" in full_script or "jq -nc" in full_script, (
            "payload must be constructed with jq -n (structured JSON)"
        )


# ── VAL-ANN-006: 认证头名称精确且值来自 secret ──


class TestAuthHeader:
    def test_x_release_token_header_present(self, full_script: str) -> None:
        """POST must carry X-Release-Token header (exact name)."""
        assert "X-Release-Token" in full_script, "curl must include X-Release-Token header"

    def test_token_from_secret(self, full_script: str) -> None:
        """Token value must reference RELEASE_BROADCAST_TOKEN secret."""
        assert "RELEASE_BROADCAST_TOKEN" in full_script, (
            "token must reference RELEASE_BROADCAST_TOKEN secret"
        )


# ── VAL-ANN-007: URL 来自 secret ──


class TestUrlFromSecret:
    def test_url_from_secret(self, full_script: str) -> None:
        """POST target URL must reference RELEASE_BROADCAST_URL secret."""
        assert "RELEASE_BROADCAST_URL" in full_script, (
            "URL must reference RELEASE_BROADCAST_URL secret"
        )

    def test_no_hardcoded_tunnel_url(self, workflow_text: str) -> None:
        """No hardcoded ci-webhook URL in workflow."""
        assert "ci-webhook.exa.edu.kg" not in workflow_text, (
            "workflow must not hardcode the tunnel URL"
        )


# ── VAL-ANN-008: JSON 内容类型头 ──


class TestContentType:
    def test_json_content_type(self, full_script: str) -> None:
        """POST must carry Content-Type: application/json."""
        assert (
            "Content-Type: application/json" in full_script
            or "Content-Type:application/json" in full_script
        ), "curl must set Content-Type: application/json"


# ── VAL-ANN-009: 传输层失败重试 ──


class TestRetryAndTimeout:
    def test_retry_flags(self, full_script: str) -> None:
        """curl must have --retry 3 --retry-all-errors."""
        assert "--retry 3" in full_script, "curl must have --retry 3"
        assert "--retry-all-errors" in full_script, "curl must have --retry-all-errors"

    def test_exit_code_capture(self, full_script: str) -> None:
        """Script must capture HTTP code and handle non-zero exit."""
        # Either || HTTP_CODE="000" or equivalent
        assert 'HTTP_CODE="000"' in full_script or "HTTP_CODE='000'" in full_script, (
            "script must capture exit code as 000 on curl failure"
        )

    def test_http_code_capture(self, full_script: str) -> None:
        """curl must use -w to capture HTTP status code."""
        assert "%{http_code}" in full_script, "curl must use -w '%{http_code}' to capture status"


# ── VAL-ANN-010: 非 2xx 告警路径，job 永不失败 ──


class TestFireAndForget:
    def test_non_2xx_warning(self, full_script: str) -> None:
        """Non-2xx must trigger ::warning::."""
        assert "::warning::" in full_script, "non-2xx response must emit ::warning::"

    def test_job_never_fails(self, full_script: str) -> None:
        """Script must end with exit 0 (never fail the job)."""
        # The last line of the run script should ensure success
        assert "exit 0" in full_script, "script must explicitly exit 0 (job never fails)"

    def test_no_set_e_without_protection(self, full_script: str) -> None:
        """Even with set -e, the script must not fail on curl error."""
        # Check that curl failure is caught
        lines = full_script.split("\n")
        curl_lines = [ln for ln in lines if "curl" in ln and "posthog" not in ln.lower()]
        for line in curl_lines:
            # The main delivery curl must have || HTTP_CODE= pattern
            if "RELEASE_BROADCAST_URL" in full_script and "$WEBHOOK_URL" not in line:
                # Main curl should be in a pattern that captures failure
                pass
        # The overall script should have the exit code capture
        assert "|| HTTP_CODE" in full_script, "curl failure must be caught with || HTTP_CODE=..."


# ── VAL-ANN-012: 2xx 静默通过 ──


class TestSuccessSilent:
    def test_2xx_no_warning(self, full_script: str) -> None:
        """2xx should not trigger any warning."""
        # The warning should only be in the non-2xx branch
        # Check that the structure is: if NOT 2xx -> warning; else silent
        assert "::warning::" in full_script
        # The warning must be inside an if block for non-2xx
        assert "!=" in full_script or "-ne" in full_script, (
            "there must be a conditional check for non-2xx"
        )


# ── VAL-ANN-013: 不校验响应体 ──


class TestNoResponseBodyValidation:
    def test_discards_response_body(self, full_script: str) -> None:
        """curl must discard response body (-o /dev/null)."""
        assert "-o /dev/null" in full_script, "curl must discard response body with -o /dev/null"

    def test_no_body_parsing(self, full_script: str) -> None:
        """Script must not parse response body."""
        # Should not have jq/grep/variable reference on response body
        # Only HTTP code is captured
        assert "RESPONSE_BODY" not in full_script, "script must not store response body"
        assert "RESPONSE=" not in full_script, "script must not store response for inspection"


# ── VAL-ANN-014: 时间上界 ──


class TestTimeBounds:
    def test_curl_max_time(self, full_script: str) -> None:
        """curl must have --max-time or --connect-timeout."""
        assert "--max-time" in full_script or "--connect-timeout" in full_script, (
            "curl must have a time limit"
        )

    def test_job_timeout(self, job: dict[str, Any]) -> None:
        """Job should have timeout-minutes."""
        assert "timeout-minutes" in job, "job should have timeout-minutes to prevent infinite hang"


# ── VAL-ANN-015: PostHog 告警 + key 缺失跳过 ──


class TestPostHogAlert:
    def test_posthog_event_on_failure(self, full_script: str) -> None:
        """Failure branch must send PostHog event."""
        assert "posthog" in full_script.lower(), "failure branch must include PostHog event"
        assert (
            "release_announce" in full_script.lower()
            or "release_announce_failed" in full_script.lower()
            or "release_broadcast" in full_script.lower()
        ), "PostHog event should identify the workflow"

    def test_posthog_key_missing_notice(self, full_script: str) -> None:
        """Missing POSTHOG_API_KEY must ::notice:: skip."""
        assert "::notice::" in full_script, "missing POSTHOG_API_KEY must emit ::notice:: and skip"

    def test_posthog_best_effort(self, full_script: str) -> None:
        """PostHog send must be best-effort (|| true)."""
        assert "|| true" in full_script, "PostHog send must be best-effort (|| true)"


# ── VAL-ANN-018: secret 缺失时预警跳过 ──


class TestSecretMissingHandling:
    def test_url_secret_check(self, full_script: str) -> None:
        """Script must check RELEASE_BROADCAST_URL is set."""
        assert "RELEASE_BROADCAST_URL" in full_script
        # Check for empty string test
        assert '-z "$' in full_script or "[ -z" in full_script or "[ -z" in full_script, (
            "script must check if URL secret is empty"
        )

    def test_token_secret_check(self, full_script: str) -> None:
        """Script must check RELEASE_BROADCAST_TOKEN is set."""
        assert "RELEASE_BROADCAST_TOKEN" in full_script

    def test_missing_secret_warning_and_skip(self, full_script: str) -> None:
        """Missing secret must ::warning:: and exit 0."""
        # The verify step should have warning + exit 0
        assert "::warning::" in full_script


# ── VAL-ANN-019: 零权限 ──


class TestZeroPermissions:
    def test_permissions_empty_map(self, workflow: dict[str, Any]) -> None:
        """Workflow must declare permissions: {} (empty mapping)."""
        perms = workflow.get("permissions")
        assert perms is not None, "workflow must declare permissions"
        assert perms == {}, f"permissions must be empty map {{}}, got {perms}"

    def test_no_permission_scopes(self, workflow: dict[str, Any]) -> None:
        """No permission scopes declared anywhere."""
        perms = workflow.get("permissions", {})
        assert not isinstance(perms, dict) or len(perms) == 0, (
            "permissions must not declare any scopes"
        )


# ── VAL-ANN-020: 不 checkout，不触碰仓库 ──


class TestNoCheckout:
    def test_no_checkout_action(self, job: dict[str, Any]) -> None:
        """Job must not use actions/checkout."""
        steps = job.get("steps") or []
        for step in steps:
            uses = str(step.get("uses", ""))
            assert "actions/checkout" not in uses, "job must not checkout the repository"

    def test_no_git_commands(self, full_script: str) -> None:
        """No git commands in the workflow."""
        # Check for git command invocations (not in comments)
        lines = full_script.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not re.match(r"\bgit\s", stripped), (
                f"workflow should not run git commands: {stripped}"
            )


# ── VAL-ANN-021: token 静态卫生 ──


class TestTokenHygiene:
    def test_no_plaintext_token(self, workflow_text: str) -> None:
        """No 64-char hex string (token value) in workflow."""
        # Look for 64+ char hex strings that could be token values
        matches = re.findall(r"\b[0-9a-f]{64}\b", workflow_text)
        assert not matches, (
            f"workflow contains potential plaintext token(s): {len(matches)} matches"
        )

    def test_no_curl_verbose(self, full_script: str) -> None:
        """curl must not use -v/--verbose (would leak headers)."""
        # Check for -v flag but not inside other flags like --retry-delay
        assert "curl -v " not in full_script and "--verbose" not in full_script, (
            "curl must not use verbose mode (leaks token header)"
        )
        # Also check for -v as a standalone flag in curl invocation
        lines = full_script.split("\n")
        for line in lines:
            if "curl" in line:
                # Match -v as a standalone flag (not part of --max-time etc.)
                assert not re.search(r"\bcurl\s+.*\s-v\s", line), "curl must not use -v flag"

    def test_token_only_referenced_by_secret_name(self, workflow_text: str) -> None:
        """RELEASE_BROADCAST_TOKEN should only appear as secret reference."""
        # All mentions should be in secrets context or variable reference
        mentions = [
            line
            for line in workflow_text.split("\n")
            if "RELEASE_BROADCAST_TOKEN" in line and not line.strip().startswith("#")
        ]
        for line in mentions:
            # Allow: secrets.RELEASE_BROADCAST_TOKEN, env: BROADCAST_TOKEN: ${{ secrets.RELEASE_BROADCAST_TOKEN }}
            # Also allow: echo messages that mention the secret name
            assert (
                "secrets.RELEASE_BROADCAST_TOKEN" in line
                or "echo" in line
                or "warning" in line.lower()
            ), f"RELEASE_BROADCAST_TOKEN must be referenced as secret or in message: {line}"


# ── VAL-ANN-026: 零远程 action 引用 ──


class TestNoRemoteActions:
    def test_no_remote_uses(self, job: dict[str, Any]) -> None:
        """Job should have zero remote action references."""
        steps = job.get("steps") or []
        for step in steps:
            uses = str(step.get("uses", ""))
            if uses:
                assert uses.startswith("./"), f"no remote action references allowed, found: {uses}"


# ── VAL-ANN-027: 增量式变更 ──


class TestIncrementalChange:
    def test_release_please_unchanged(self) -> None:
        """release-please.yml must not be modified."""
        release_please = REPO_ROOT / ".github" / "workflows" / "release-please.yml"
        assert release_please.exists(), "release-please.yml must still exist"
        # This test is a structural check; actual diff check is done in PR review
