"""命名契约测试（architecture.md §3）

这些字符串构成隐式契约网络，任何静默改动会杀死 auto-merge/watchdog。
infra-core 侧对 shipped workflow 模板断言字节级一致。
"""

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent

# 契约：workflow 名（auto-merge workflow_run 依赖）
CONTRACT_WORKFLOW_NAMES = {
    ".github/workflows/ci.yml": "CI",
    ".github/workflows/evolution-governance.yml": "Evolution Governance",
}

# 契约：governance 门禁 job 显示名（branch protection required check）
CONTRACT_GOVERNANCE_JOB_NAME = "Block non-owner governance modifications"

# 契约：ci-ok 聚合 job key（branch protection required check）
CONTRACT_CI_OK_JOB_KEY = "ci-ok"


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


class TestWorkflowNameContract:
    def test_ci_workflow_name(self):
        assert re.search(r"^name:\s*CI\s*$", _read(".github/workflows/ci.yml"), re.MULTILINE)

    def test_governance_workflow_name(self):
        assert re.search(
            r"^name:\s*Evolution Governance\s*$",
            _read(".github/workflows/evolution-governance.yml"),
            re.MULTILINE,
        )


class TestGovernanceJobNameContract:
    def test_governance_job_display_name(self):
        content = _read(".github/workflows/evolution-governance.yml")
        assert f"name: {CONTRACT_GOVERNANCE_JOB_NAME}" in content


class TestCiOkJobKeyContract:
    def test_ci_ok_job_key(self):
        content = _read(".github/workflows/ci.yml")
        assert re.search(r"^  ci-ok:\s*$", content, re.MULTILINE)


class TestGovernanceActionDefaults:
    def test_composite_action_defaults(self):
        content = _read("actions/governance-check/action.yml")
        assert "default: 'hdot123'" in content
        # 默认受保护模式覆盖 infra-core 自身 governance 路径
        for fragment in (
            ".evolution/**",
            ".github/workflows/**",
            "src/infra_core/engine/**",
            "webhook-scripts/**",
        ):
            assert fragment in content

    def test_governance_workflow_uses_shipped_action(self):
        """governance workflow 必须执行 shipped action（VAL-SCAF-006 路径感知判定），
        不能回退为只查作者不查路径的内联脚本"""
        content = _read(".github/workflows/evolution-governance.yml")
        assert "hdot123-org/infra-core/actions/governance-check@main" in content
        # 不得残留旧的内联作者检查（只对比作者、无路径感知）
        assert 'PR_AUTHOR="${{ github.event.pull_request.user.login }}"' not in content

    def test_governance_workflow_uses_pull_request_target(self):
        """pull_request_target 从 base 运行（受保护门禁不能被 PR 自身改写）"""
        content = _read(".github/workflows/evolution-governance.yml")
        assert "pull_request_target" in content


class TestGovernanceActionScriptPath:
    """action.yml run 行引用的脚本必须在 action 目录内且真实存在。

    修复 M1 scrutiny 发现的 blocking 缺陷：原路径 `../governance_check/governance_check.py`
    双重错误——越出 action 根 + 下划线目录名不匹配（实际是 governance-check）。
    首次真实调用即 crash-deny，M4 全部门禁切换 PR 都会触发。
    """

    def test_action_yml_references_script_within_action_dir(self):
        """action.yml 的 run 块不得包含 `..` 越出 action 根目录"""
        content = _read("actions/governance-check/action.yml")
        # 提取 run: 块（YAML 多行字符串）
        run_match = re.search(r"run:\s*\|(.+?)(?=\n\w|\Z)", content, re.DOTALL)
        assert run_match, "action.yml 必须包含 run 块"
        run_block = run_match.group(1)
        # 不得包含路径穿越
        assert ".." not in run_block or "../" not in run_block, (
            f"action.yml run 块包含路径穿越（..）：{run_block}"
        )

    def test_action_yml_script_path_resolves_to_existing_file(self):
        """action.yml 引用的脚本路径必须在 repo 树中真实存在"""
        content = _read("actions/governance-check/action.yml")
        # 查找 $GITHUB_ACTION_PATH/<script> 模式
        script_match = re.search(r"\$GITHUB_ACTION_PATH/(\S+\.py)", content)
        assert script_match, "action.yml 必须引用 $GITHUB_ACTION_PATH/<script>.py"
        script_name = script_match.group(1)
        # 验证脚本文件存在
        script_path = REPO_ROOT / "actions" / "governance-check" / script_name
        assert script_path.exists(), (
            f"action.yml 引用的脚本不存在：{script_path.relative_to(REPO_ROOT)}"
        )

    def test_action_yml_uses_correct_script_name(self):
        """action.yml 必须引用 governance_check.py（与目录同名但下划线）"""
        content = _read("actions/governance-check/action.yml")
        assert "$GITHUB_ACTION_PATH/governance_check.py" in content, (
            "action.yml 必须引用 $GITHUB_ACTION_PATH/governance_check.py"
        )


class TestGovernanceModuleDefaults:
    def test_module_defaults_match_composite_action(self):
        from infra_core.governance import DEFAULT_OWNER_LOGIN, DEFAULT_PROTECTED_PATTERNS

        assert DEFAULT_OWNER_LOGIN == "hdot123"
        assert DEFAULT_PROTECTED_PATTERNS == (
            ".evolution/**",
            ".github/workflows/**",
            "src/infra_core/engine/**",
            "webhook-scripts/**",
        )


class TestBranchCleanupCompositeContextGuard:
    """复合 action 上下文守卫：vars/secrets context 在 composite action 内不可用。

    根因（INFRA-585，2026-08-27）：actions/branch-cleanup/action.yml 使用
    ${{ vars.BRANCH_AGE_* }} 导致模板校验失败（Unrecognized named-value: vars）。
    vars/secrets context 仅在 workflow 层合法，composite action 必须通过
    inputs 接收值（caller 在 workflow 层经 with: 转发 vars.BRANCH_AGE_*）。
    actionlint 无法检出此问题，仅真实执行暴露。本测试防止回退。
    """

    ACTION_YML = "actions/branch-cleanup/action.yml"

    def _non_comment_lines(self) -> list[tuple[int, str]]:
        """返回 (行号, 行内容) 列表，跳过注释行。"""
        lines = _read(self.ACTION_YML).split("\n")
        return [(i, line) for i, line in enumerate(lines, 1) if not line.strip().startswith("#")]

    def test_action_yml_no_vars_context(self):
        """action.yml 不得引用 vars.* context（composite action 内不合法）"""
        for i, line in self._non_comment_lines():
            assert "${{ vars." not in line, (
                f"action.yml 第 {i} 行包含 vars.* context 引用（composite action 内不合法）：{line}"
            )

    def test_action_yml_no_secrets_context(self):
        """action.yml 不得直接引用 secrets.* context（必须通过 inputs 传入）"""
        for i, line in self._non_comment_lines():
            assert "${{ secrets." not in line, (
                f"action.yml 第 {i} 行包含 secrets.* context 引用（应通过 inputs 传入）：{line}"
            )

    def test_action_yml_has_branch_age_inputs(self):
        """action.yml 必须声明 branch-age-* inputs（接收阈值）"""
        content = _read(self.ACTION_YML)
        for input_name in (
            "branch-age-merged-hours",
            "branch-age-closed-hours",
            "branch-age-orphan-hours",
        ):
            assert input_name in content, f"action.yml 缺少 input: {input_name}"

    def test_action_yml_uses_inputs_for_branch_age(self):
        """action.yml env 块必须使用 inputs.* 而非 vars.*"""
        content = _read(self.ACTION_YML)
        assert "${{ inputs.branch-age-merged-hours }}" in content
        assert "${{ inputs.branch-age-closed-hours }}" in content
        assert "${{ inputs.branch-age-orphan-hours }}" in content
