"""F7 平台漂移守护测试 — repo 级 Actions 策略线上值断言。

模式：复用 TestRepoVariablesExistence（test_naming_contract.py:886）的
gh subprocess + 优雅降级模式。

断言 5 组线上值：
1. allowed_actions=selected, sha_pinning_required=true, enabled=true
2. selected-actions 三元组：github_owned_allowed=true, verified_allowed=false,
   patterns_allowed 精确集合 ["hdot123-org/infra-core/**", "googleapis/*"]
3. approval_policy=all_external_contributors
4. default_workflow_permissions=read
5. can_approve_pull_request_reviews=false

凭证现实：CI pytest job 无 GH_TOKEN 注入且 GITHUB_TOKEN 无 administration
读权限 → CI 内 skip 是设计内降级，非 skip 证据 = 本地带凭证运行。

关键：selected-actions 端点 409 = 漂移回 all → FAIL，不得归类为 skip。

禁止向 pytest job 注入 DISPATCH_TOKEN（安全回退）。
"""

import json
import shutil
import subprocess

import pytest

REPO = "hdot123-org/infra-core"


def _gh_api_available() -> bool:
    """Check if gh CLI and API credentials are available."""
    if shutil.which("gh") is None:
        return False
    probe = subprocess.run(
        ["gh", "api", "repos/hdot123-org/infra-core", "--jq", ".id"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return probe.returncode == 0


def _gh_api_get(endpoint: str) -> dict:
    """GET a GitHub API endpoint via gh cli, return parsed JSON."""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/{endpoint}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gh api GET {endpoint} failed (rc={result.returncode}): {result.stderr.strip()[:200]}"
        )
    return json.loads(result.stdout)


def _gh_api_get_raw(endpoint: str) -> subprocess.CompletedProcess:
    """GET a GitHub API endpoint, return raw CompletedProcess for status code inspection."""
    return subprocess.run(
        ["gh", "api", f"repos/{REPO}/{endpoint}"],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级，非 drift 检测失效）",
)
class TestActionsPermissionsPolicy:
    """F7 平台策略断言 — /actions/permissions 端点。"""

    def test_actions_permissions_selected_and_sha_pinned(self):
        """VAL-M3-001: allowed_actions=selected, sha_pinning_required=true, enabled=true."""
        data = _gh_api_get("actions/permissions")
        assert data["enabled"] is True, f"enabled 应为 True, 实际 {data['enabled']}"
        assert data["allowed_actions"] == "selected", (
            f"allowed_actions 应为 'selected', 实际 '{data['allowed_actions']}'"
        )
        assert data["sha_pinning_required"] is True, (
            f"sha_pinning_required 应为 True, 实际 {data['sha_pinning_required']}"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级，非 drift 检测失效）",
)
class TestSelectedActionsAllowlist:
    """F7 allowlist 三元组精确断言 — /actions/permissions/selected-actions。

    关键：该端点在 allowed_actions=all 时返回 409（Conflict）。
    409 = 漂移回 all → FAIL，不得归类为 skip。
    """

    def test_selected_actions_allowlist_exact(self):
        """VAL-M3-002: github_owned=true, verified=false, patterns 精确集合。"""
        result = _gh_api_get_raw("actions/permissions/selected-actions")

        # 409 = allowed_actions 漂移回 all → FAIL
        if result.returncode != 0 and "409" in result.stderr:
            pytest.fail(
                "selected-actions 端点返回 409 = allowed_actions 漂移回 all，"
                "这是漂移 FAIL 不是环境 skip"
            )

        # 其他非零返回 = 环境问题，raise 给上层 skip 逻辑
        if result.returncode != 0:
            raise RuntimeError(
                f"gh api GET selected-actions 异常失败: {result.stderr.strip()[:200]}"
            )

        data = json.loads(result.stdout)

        assert data["github_owned_allowed"] is True, (
            f"github_owned_allowed 应为 True, 实际 {data['github_owned_allowed']}"
        )
        assert data["verified_allowed"] is False, (
            f"verified_allowed 应为 False, 实际 {data['verified_allowed']}"
        )

        expected_patterns = {"hdot123-org/infra-core/**", "googleapis/*"}
        actual_patterns = set(data["patterns_allowed"])
        assert actual_patterns == expected_patterns, (
            f"patterns_allowed 精确集合不匹配: "
            f"期望 {sorted(expected_patterns)}, 实际 {sorted(actual_patterns)}"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级，非 drift 检测失效）",
)
class TestForkPRApprovalPolicy:
    """F7 fork PR 审批策略断言。"""

    def test_fork_pr_approval_policy(self):
        """VAL-M3-003: approval_policy=all_external_contributors."""
        data = _gh_api_get("actions/permissions/fork-pr-contributor-approval")
        assert data["approval_policy"] == "all_external_contributors", (
            f"approval_policy 应为 'all_external_contributors', 实际 '{data['approval_policy']}'"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级，非 drift 检测失效）",
)
class TestDefaultWorkflowPermissions:
    """F7 GITHUB_TOKEN 默认权限防回退断言。"""

    def test_default_workflow_permissions_read(self):
        """VAL-M3-004: default_workflow_permissions=read, can_approve=false."""
        data = _gh_api_get("actions/permissions/workflow")
        assert data["default_workflow_permissions"] == "read", (
            f"default_workflow_permissions 应为 'read', "
            f"实际 '{data['default_workflow_permissions']}'"
        )
        assert data["can_approve_pull_request_reviews"] is False, (
            f"can_approve_pull_request_reviews 应为 False, "
            f"实际 {data['can_approve_pull_request_reviews']}"
        )
