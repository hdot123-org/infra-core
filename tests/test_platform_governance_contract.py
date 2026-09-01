"""F7/F8 平台漂移守护测试 — repo 级 Actions 策略 + Rulesets 迁移线上值断言。

模式：复用 TestRepoVariablesExistence（test_naming_contract.py:886）的
gh subprocess + 优雅降级模式。

F7 断言 5 组线上值：
1. allowed_actions=selected, sha_pinning_required=true, enabled=true
2. selected-actions 三元组：github_owned_allowed=true, verified_allowed=false,
   patterns_allowed 精确集合 ["hdot123-org/infra-core/**", "googleapis/*"]
3. approval_policy=all_external_contributors
4. default_workflow_permissions=read
5. can_approve_pull_request_reviews=false

F8 断言面（Rulesets 迁移 + 合并设置）：
- ruleset main-branch-protection 存在、active、target/conditions 正确
- 五类规则参数齐全（required_status_checks/linear_history/deletion/
  non_fast_forward/pull_request）
- bypass_actors 空（凭证分支：write+ 断言、read-only skip）
- classic protection 404
- /rules/branches/main 聚合生效
- 合并设置六字段（squash-only + delete/auto/update）
- 静态锚点（INFRA-715）：F8 期望值防篡改双保险，无凭证环境（含 CI）生效

凭证现实：CI pytest job 无 GH_TOKEN 注入且 GITHUB_TOKEN 无 administration
读权限 → CI 内 skip 是设计内降级，非 skip 证据 = 本地带凭证运行。

关键：selected-actions 端点 409 = 漂移回 all → FAIL，不得归类为 skip。

禁止向 pytest job 注入 DISPATCH_TOKEN（安全回退）。

VAL-M3-012 补充（2026-09-01，INFRA-713）：allowlist 放行面 ⊇ 仓库远程
uses owner 集（无隐性断路）。静态锚点断言无凭证也生效（CI 内可跑），
线上断言捕获 allowlist pattern 被删/改窄的漂移。

INFRA-715 补充（2026-09-01）：F8 期望值静态锚点（TestF8StaticAnchors）。
F8 live 断言在 CI 内全 SKIPPED（无凭证），期望值锚点此前在无凭证环境
零防护；静态锚点对齐 #168 F7 先例，防期望值被篡改后 live 断言静默放行。
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
# (#168 合入，用户并行会话)
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


# ---------------------------------------------------------------------------
# F8 — Rulesets 迁移漂移守护测试
# ---------------------------------------------------------------------------

# enforcement 归一化集合：API 响应可能返回 "enabled" 或 "active"，语义等价
_ENFORCEMENT_ACTIVE = {"active", "enabled"}

# F8 期望值锚点（INFRA-715）— live 断言的唯一期望来源，静态锚点测试钉死。
# 结构：live 断言消费锚点常量（改线上期望必改锚点）；TestF8StaticAnchors
# 用独立字面量钉死锚点（改锚点必过静态断言这关）。单点篡改必然留红：
# 只改锚点 → 静态断言红；只改静态字面量 → 与锚点不一致即红。两处同改
# 则等同显式重写治理基线，须过评审。
_F8_RULESET_NAME = "main-branch-protection"
_F8_REF_NAME_INCLUDE = ("~DEFAULT_BRANCH",)
_F8_RSC_CHECKS_ANCHOR = frozenset({("ci-ok", 15368), ("qa-ok", 15368)})
_F8_ALLOWED_MERGE_METHODS_ANCHOR = ("squash",)
_F8_RULE_TYPES_ANCHOR = frozenset(
    {
        "required_status_checks",
        "required_linear_history",
        "deletion",
        "non_fast_forward",
        "pull_request",
    }
)
_F8_MERGE_SETTINGS_ANCHOR = {
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "delete_branch_on_merge": True,
    "allow_auto_merge": True,
    "allow_update_branch": True,
}


def _have_write_credentials() -> bool:
    """检测是否有 write+ 凭证（可读取 bypass_actors 字段）。

    bypass_actors 仅 write+ 凭证可见；GITHUB_TOKEN（read-only）下该字段
    不可见或返回歧义空值。有此凭证时做 bypass_actors 断言，否则 skip 该子断言。
    """
    if shutil.which("gh") is None:
        return False
    probe = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode != 0:
        return False
    token = probe.stdout.strip()
    # PAT (ghp_*) 或 fine-grained (github_pat_*) 通常有 write 权限
    # GITHUB_TOKEN 是 eyJ... 格式（JWT），通常只读 administration
    return token.startswith(("ghp_", "github_pat_"))


def _get_rulesets_list() -> list[dict]:
    """GET rulesets with includes_parents=false to exclude org-level rulesets."""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/rulesets?includes_parents=false"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GET rulesets failed: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def _get_ruleset_detail(ruleset_id: int) -> dict:
    """GET a single ruleset detail by ID."""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/rulesets/{ruleset_id}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GET rulesets/{ruleset_id} failed: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def _find_ruleset_id() -> int:
    """Find the ID of the main-branch-protection ruleset."""
    rulesets = _get_rulesets_list()
    matching = [rs for rs in rulesets if rs.get("name") == "main-branch-protection"]
    if not matching:
        raise AssertionError("main-branch-protection ruleset not found")
    return matching[0]["id"]


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级）",
)
class TestRulesetsExistence:
    """VAL-M3-013: ruleset 存在、active、target/conditions 正确。"""

    def test_main_branch_protection_ruleset_exists(self):
        """ruleset main-branch-protection 存在且 enforcement 归一化为 active。"""
        rulesets = _get_rulesets_list()
        matching = [rs for rs in rulesets if rs.get("name") == _F8_RULESET_NAME]
        assert len(matching) == 1, (
            f"应恰好有一个 {_F8_RULESET_NAME} ruleset, 找到 {len(matching)} 个"
        )
        rs = matching[0]
        # enforcement 归一化: active/enabled 等价
        assert rs["enforcement"] in _ENFORCEMENT_ACTIVE, (
            f"enforcement 应为 active/enabled, 实际 '{rs['enforcement']}'"
        )
        assert rs["target"] == "branch", f"target 应为 'branch', 实际 '{rs['target']}'"

    def test_ruleset_conditions_default_branch(self):
        """conditions.ref_name.include = ['~DEFAULT_BRANCH'], exclude = []."""
        detail = _get_ruleset_detail(_find_ruleset_id())
        conditions = detail.get("conditions", {})
        ref_name = conditions.get("ref_name", {})
        assert ref_name.get("include") == list(_F8_REF_NAME_INCLUDE), (
            f"ref_name.include 应为 {list(_F8_REF_NAME_INCLUDE)}, 实际 {ref_name.get('include')}"
        )
        assert ref_name.get("exclude") == [], (
            f"ref_name.exclude 应为 [], 实际 {ref_name.get('exclude')}"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级）",
)
class TestRulesetsFiveRuleTypes:
    """VAL-M3-014: 五类规则齐全且参数正确。"""

    def test_required_status_checks_parameters(self):
        """required_status_checks: ci-ok + qa-ok, integration_id=15368, strict=true."""
        detail = _get_ruleset_detail(_find_ruleset_id())
        rsc_rules = [r for r in detail["rules"] if r["type"] == "required_status_checks"]
        assert len(rsc_rules) == 1, "应有恰好一个 required_status_checks 规则"
        params = rsc_rules[0]["parameters"]

        checks = params["required_status_checks"]
        check_set = {(c["context"], c["integration_id"]) for c in checks}
        expected = set(_F8_RSC_CHECKS_ANCHOR)
        assert check_set == expected, (
            f"required_status_checks 集合不匹配: 期望 {expected}, 实际 {check_set}"
        )
        assert params["strict_required_status_checks_policy"] is True, (
            "strict_required_status_checks_policy 应为 True"
        )
        assert params["do_not_enforce_on_create"] is False, "do_not_enforce_on_create 应为 False"

    def test_required_linear_history_exists(self):
        """required_linear_history 规则存在（无参数）。"""
        detail = _get_ruleset_detail(_find_ruleset_id())
        rule_types = [r["type"] for r in detail["rules"]]
        assert "required_linear_history" in rule_types, (
            f"rules 应包含 required_linear_history, 实际规则类型: {rule_types}"
        )

    def test_deletion_rule_exists(self):
        """deletion 规则存在（禁删分支）。"""
        detail = _get_ruleset_detail(_find_ruleset_id())
        rule_types = [r["type"] for r in detail["rules"]]
        assert "deletion" in rule_types, f"rules 应包含 deletion, 实际规则类型: {rule_types}"

    def test_non_fast_forward_rule_exists(self):
        """non_fast_forward 规则存在（禁 force push）。"""
        detail = _get_ruleset_detail(_find_ruleset_id())
        rule_types = [r["type"] for r in detail["rules"]]
        assert "non_fast_forward" in rule_types, (
            f"rules 应包含 non_fast_forward, 实际规则类型: {rule_types}"
        )

    def test_pull_request_rule_squash_only(self):
        """pull_request 规则: count=0, allowed_merge_methods=['squash']。"""
        detail = _get_ruleset_detail(_find_ruleset_id())
        pr_rules = [r for r in detail["rules"] if r["type"] == "pull_request"]
        assert len(pr_rules) == 1, "应有恰好一个 pull_request 规则"
        params = pr_rules[0]["parameters"]
        assert params["required_approving_review_count"] == 0, (
            f"required_approving_review_count 应为 0, 实际 {params['required_approving_review_count']}"
        )
        expected_methods = list(_F8_ALLOWED_MERGE_METHODS_ANCHOR)
        assert params["allowed_merge_methods"] == expected_methods, (
            f"allowed_merge_methods 应为 {expected_methods}, 实际 {params['allowed_merge_methods']}"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级）",
)
class TestRulesetsBypassActors:
    """VAL-M3-015: bypass_actors 为空（无人可绕过）。

    bypass_actors 仅 write+ 凭证可见。凭证分支处理：
    - write+ 凭证（PAT）→ 断言 bypass_actors == []
    - read-only 凭证（GITHUB_TOKEN）→ skip 该子断言并注明
    """

    def test_bypass_actors_empty_with_write_credentials(self):
        """write+ 凭证下 bypass_actors 必须为空数组。"""
        if not _have_write_credentials():
            pytest.skip(
                "bypass_actors 仅 write+ 凭证可见; "
                "当前为 read-only 凭证, 跳过该子断言 (见 VAL-M3-015 凭证分支)"
            )
        detail = _get_ruleset_detail(_find_ruleset_id())
        bypass = detail.get("bypass_actors", None)
        assert bypass is not None, "write+ 凭证下 bypass_actors 字段应可见"
        assert bypass == [], f"bypass_actors 应为空数组 (无人可绕过), 实际: {bypass}"


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级）",
)
class TestClassicProtectionDeleted:
    """VAL-M3-016: classic branch protection 已删除 (GET 404)。"""

    def test_classic_protection_returns_404(self):
        """GET branches/main/protection 应返回 404。"""
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/branches/main/protection"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, "classic protection GET 应失败 (404), 但返回成功"
        assert "404" in result.stderr or "Branch not protected" in result.stderr, (
            f"classic protection 应返回 404, 实际 stderr: {result.stderr[:200]}"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级）",
)
class TestAggregatedRules:
    """VAL-M3-017: /rules/branches/main 聚合规则生效。"""

    def test_aggregated_rules_five_types(self):
        """聚合规则包含五类规则。"""
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/rules/branches/main"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"GET rules/branches/main failed: {result.stderr[:200]}")
        rules = json.loads(result.stdout)
        rule_types = {r["type"] for r in rules}
        expected_types = set(_F8_RULE_TYPES_ANCHOR)
        assert expected_types.issubset(rule_types), (
            f"聚合规则缺类型: 期望 {expected_types}, 实际 {rule_types}"
        )


@pytest.mark.skipif(
    not _gh_api_available(),
    reason="gh CLI 不可用或无凭证（CI 设计内降级）",
)
class TestMergeSettingsSquashOnly:
    """VAL-M3-018: 合并设置收敛为 squash-only + 自动化配套。"""

    def test_merge_settings_six_fields(self):
        """六字段精确匹配: squash-only + delete/auto/update branch。"""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{REPO}",
                "--jq",
                '{"allow_squash_merge":.allow_squash_merge,'
                '"allow_merge_commit":.allow_merge_commit,'
                '"allow_rebase_merge":.allow_rebase_merge,'
                '"delete_branch_on_merge":.delete_branch_on_merge,'
                '"allow_auto_merge":.allow_auto_merge,'
                '"allow_update_branch":.allow_update_branch}',
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"GET repo failed: {result.stderr[:200]}")
        data = json.loads(result.stdout)

        expected = dict(_F8_MERGE_SETTINGS_ANCHOR)
        for field, exp_val in expected.items():
            assert data[field] == exp_val, f"{field} 应为 {exp_val}, 实际 {data[field]}"


# ---------------------------------------------------------------------------
# F8 静态锚点（INFRA-715）— 期望值防篡改，无凭证环境（含 CI）也生效
# ---------------------------------------------------------------------------
# 现实：上方 F8 live 断言（VAL-M3-013~018）全部依赖 gh 凭证，CI pytest
# job 无 GH_TOKEN → CI 内 11 个 F8 测试全 SKIPPED，期望值在无凭证环境
# 零防护。若 live 断言内联期望值，篡改期望（如 allow_merge_commit
# False→True）后断言与线上漂移一致，漂移被静默放行。
# 本节的防篡改结构（对齐 #168 为 F7 补 TestAllowlistCoverageStatic 的
# 先例，并升级为锚点单源）：
# 1. live 断言不写内联期望，只消费锚点常量 → 改线上期望必改锚点；
# 2. TestF8StaticAnchors 用独立字面量钉死锚点常量 → 改锚点在 CI 内即红
#    （无凭证也跑），先于 live 断言静默失效暴露。
# 单点篡改必然留红：只改锚点 → 静态断言红；两处同改 = 显式重写治理
# 基线，须过评审。


class TestF8StaticAnchors:
    """F8 期望值静态锚点断言 — 防篡改双保险，无凭证环境（含 CI）生效。"""

    def test_merge_settings_anchor_unchanged(self) -> None:
        """合并设置六字段锚点未被篡改（squash-only + delete/auto/update）。"""
        assert _F8_MERGE_SETTINGS_ANCHOR == {
            "allow_squash_merge": True,
            "allow_merge_commit": False,
            "allow_rebase_merge": False,
            "delete_branch_on_merge": True,
            "allow_auto_merge": True,
            "allow_update_branch": True,
        }, (
            f"F8 合并设置锚点被修改: {_F8_MERGE_SETTINGS_ANCHOR} — 平台层 squash-only "
            "收敛（VAL-M3-018）是治理基线，改锚点须过评审"
        )

    def test_ruleset_identity_anchors(self) -> None:
        """ruleset 名称、enforcement 归一化、ref_name 条件锚点未被篡改。"""
        assert _F8_RULESET_NAME == "main-branch-protection", (
            f"ruleset 名称锚点被修改: {_F8_RULESET_NAME}"
        )
        assert _ENFORCEMENT_ACTIVE == {"active", "enabled"}, (
            f"enforcement 归一化锚点被修改: {sorted(_ENFORCEMENT_ACTIVE)} — "
            "收窄该集合会让 disabled/evaluate 形态漏判"
        )
        assert _F8_REF_NAME_INCLUDE == ("~DEFAULT_BRANCH",), (
            f"ref_name.include 锚点被修改: {_F8_REF_NAME_INCLUDE} — "
            "改条件会让 ruleset 脱离默认分支保护面"
        )

    def test_required_status_checks_anchor(self) -> None:
        """required_status_checks 锚点 = {(ci-ok, 15368), (qa-ok, 15368)}。"""
        assert _F8_RSC_CHECKS_ANCHOR == {("ci-ok", 15368), ("qa-ok", 15368)}, (
            f"required_status_checks 锚点被修改: {sorted(_F8_RSC_CHECKS_ANCHOR)} — "
            "删 check（如 qa-ok）会静默拆掉 merge 门禁"
        )

    def test_merge_methods_and_rule_types_anchor(self) -> None:
        """allowed_merge_methods 仅 squash；五类规则类型齐全。"""
        assert _F8_ALLOWED_MERGE_METHODS_ANCHOR == ("squash",), (
            f"allowed_merge_methods 锚点被修改: {_F8_ALLOWED_MERGE_METHODS_ANCHOR} — "
            "扩为 merge/rebase 即拆掉 squash-only 基线"
        )
        assert _F8_RULE_TYPES_ANCHOR == {
            "required_status_checks",
            "required_linear_history",
            "deletion",
            "non_fast_forward",
            "pull_request",
        }, (
            f"五类规则类型锚点被修改: {sorted(_F8_RULE_TYPES_ANCHOR)} — 删任一规则类型"
            "（如 deletion）会静默放开对应保护面"
        )
