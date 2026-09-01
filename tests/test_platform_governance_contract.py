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

VAL-M3-012 补充（2026-09-01，INFRA-713）：allowlist 放行面 ⊇ 仓库远程
uses owner 集（无隐性断路）。静态锚点断言无凭证也生效（CI 内可跑），
线上断言捕获 allowlist pattern 被删/改窄的漂移。
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

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
            f"default_workflow_permissions 应为 'read', 实际 '{data['default_workflow_permissions']}'"
        )
        assert data["can_approve_pull_request_reviews"] is False, (
            f"can_approve_pull_request_reviews 应为 False, 实际 {data['can_approve_pull_request_reviews']}"
        )


# ---------------------------------------------------------------------------
# VAL-M3-012 — allowlist 放行面 ⊇ 远程 uses owner 集（无隐性断路）
# ---------------------------------------------------------------------------

# allowlist 放行面（线上 selected-actions 的解析形态）：
#   - github_owned_allowed=true 放行 actions/* owner
#   - patterns_allowed 中 hdot123-org/infra-core/** 放行 hdot123-org owner
#   - patterns_allowed 中 googleapis/* 放行 googleapis owner
ALLOWED_OWNERS = frozenset({"actions", "hdot123-org", "googleapis"})

# 守护测试自身声明的 allowlist 放行面锚点（静态断言用，与线上值双保险：
# 若有人改此常量绕过线上断言，模式漂移断言仍会捕获 pattern 变化）
_PATTERN_ANCHORS = frozenset({"hdot123-org/infra-core/**", "googleapis/*"})

# 与 test_uses_sha_pinning_contract.py 相同的扫描面
REPO_ROOT = Path(__file__).parent.parent
SCAN_DIRS = [
    REPO_ROOT / ".github" / "workflows",
    REPO_ROOT / ".github" / "actions",
    REPO_ROOT / "actions",
]

# owner 为 uses 值的第一段（本地 ./ 与 docker:// 由调用方豁免）
_OWNER_RE = re.compile(r"^([^/@\s]+)/")


def _collect_remote_uses_owners() -> set[str]:
    """收集仓库全部远程 uses 引用的 owner 集合。

    解析面与 TestUsesShaPinning 保持一致（同正则、同注释行跳过、同扫描
    目录）：`uses: <value>` 行内 search 匹配，value 截止于空白或 #，天然
    兼容列表形态 `- uses: x@sha` 与行尾版本注释 `# v5`；本地 ./ 与
    docker:// 引用豁免（FNM_PATHNAME 断路面须与平台真实解析面一致）。
    """
    owners: set[str] = set()
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for pattern in ("*.yml", "*.yaml"):
            for yaml_file in scan_dir.rglob(pattern):
                for line in yaml_file.read_text(encoding="utf-8").split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    match = re.search(r"uses:\s*([^\s#]+)", stripped)
                    if not match:
                        continue
                    uses_value = match.group(1)
                    if uses_value.startswith(("./", "docker://")):
                        continue
                    owner_match = _OWNER_RE.match(uses_value)
                    if owner_match:
                        owners.add(owner_match.group(1))
    return owners


class TestAllowlistCoverageStatic:
    """VAL-M3-012 静态锚点断言 — 无凭证环境（含 CI）也生效。"""

    def test_allowlist_anchor_constants_unchanged(self) -> None:
        """放行面锚点常量未被篡改（防改常量绕过线上断言）。"""
        assert _PATTERN_ANCHORS == {"hdot123-org/infra-core/**", "googleapis/*"}, (
            f"allowlist pattern 锚点被修改: {sorted(_PATTERN_ANCHORS)} — "
            "扩 allowlist 须同步改 VAL-M3-002 的线上断言与本锚点"
        )
        assert ALLOWED_OWNERS == {"actions", "hdot123-org", "googleapis"}, (
            f"ALLOWED_OWNERS 被修改: {sorted(ALLOWED_OWNERS)} — 扩 owner 面须同步改线上断言与本常量"
        )

    def test_remote_uses_owners_within_allowlist(self) -> None:
        """仓库全部远程 uses 的 owner ⊆ allowlist 放行面。

        违规形态：新增 allowlist 外 owner 的 action 引用（该 job 会被平台
        拒绝，隐性断路）。本断言在 PR 内即红，先于线上 run 暴露。
        """
        owners = _collect_remote_uses_owners()
        # 扫描面必须非空：扫描面意外失效（目录改名/rglob 失配）是漏报形态
        assert owners, "扫描面为空——uses 收集逻辑失效或目录结构漂移（漏报风险）"
        out_of_allowlist = owners - ALLOWED_OWNERS
        assert not out_of_allowlist, (
            f"发现 allowlist 外 owner 的远程 uses 引用（平台将拒绝运行，隐性断路）: "
            f"{sorted(out_of_allowlist)}；全量 owner 集: {sorted(owners)}；"
            f"放行面: github_owned(actions) + patterns {sorted(_PATTERN_ANCHORS)}。"
            "修复方向二选一：移除该引用，或扩 allowlist 并同步本文件线上断言。"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级，非 drift 检测失效）",
)
class TestAllowlistCoverageLive:
    """VAL-M3-012 线上放行面断言 — 捕获 allowlist pattern 被删/改窄的漂移。"""

    def test_live_patterns_cover_repo_owners(self) -> None:
        """线上 patterns_allowed 须覆盖仓库 owner 集（不含 github_owned 面）。

        期望线上 patterns 精确等于锚点集（VAL-M3-002 亦断言），此处从
        放行面视角做冗余断言：pattern 被删或改窄会让对应 owner 的全部
        uses 引用变为隐性断路。
        """
        result = _gh_api_get_raw("actions/permissions/selected-actions")

        # 409 = allowed_actions 漂移回 all → FAIL（同 VAL-M3-002 判定）
        if result.returncode != 0 and "409" in result.stderr:
            pytest.fail(
                "selected-actions 端点返回 409 = allowed_actions 漂移回 all，"
                "这是漂移 FAIL 不是环境 skip"
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"gh api GET selected-actions 异常失败: {result.stderr.strip()[:200]}"
            )

        data = json.loads(result.stdout)
        if not data.get("github_owned_allowed"):
            pytest.fail(
                "github_owned_allowed=false — actions/* owner 失去放行，"
                f"owner 集 {sorted(_collect_remote_uses_owners())} 将大面积断路"
            )

        live_patterns = set(data.get("patterns_allowed") or [])
        patterns_missing = _PATTERN_ANCHORS - live_patterns
        assert not patterns_missing, (
            f"线上 allowlist pattern 缺失（对应 owner 的 uses 引用将断路）: "
            f"{sorted(patterns_missing)}；线上 patterns: {sorted(live_patterns)}"
        )
