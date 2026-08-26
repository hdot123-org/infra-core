"""命名契约测试（architecture.md §3）

这些字符串构成隐式契约网络，任何静默改动会杀死 auto-merge/watchdog。
infra-core 侧对 shipped workflow 模板断言字节级一致。
"""

import re
from pathlib import Path

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
