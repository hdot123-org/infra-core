"""M4 branch-cleanup 双副本漂移防护（INFRA-583）

背景：actions/branch-cleanup/ 内嵌脚本必须自包含（消费仓在任意 base
使用 action，不能假设 infra-core 已安装，故 action 自带脚本副本）。
src/infra_core/shell/ 是移植来源的权威副本，被 tests/test_branch_cleanup*.py
的行为测试覆盖。两份副本当前字节一致（PR #26 从 src 复制而来）。

契约：任意一侧的静默改动都会漂移 action 实际执行的行为与被测行为。
本测试锁定字节级一致，改动必须双侧同步并经由 PR 评审。
先例：actions/governance-check 等价性由 test_governance.py 锁定。
"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent

# (action 副本, src 权威副本) —— 均为 git index 中的 100755/100644 文件
COPIED_FILES = [
    ("branch_cleanup.sh", "actions/branch-cleanup/branch_cleanup.sh",
     "src/infra_core/shell/branch_cleanup.sh"),
    ("branch_cleanup_issue.sh", "actions/branch-cleanup/branch_cleanup_issue.sh",
     "src/infra_core/shell/branch_cleanup_issue.sh"),
    ("branch_cleanup_retired.txt", "actions/branch-cleanup/branch_cleanup_retired.txt",
     "src/infra_core/shell/branch_cleanup_retired.txt"),
]


class TestBranchCleanupActionCopies:
    """action 内嵌脚本与 src 权威副本字节一致（drift 防护）"""

    @pytest.mark.parametrize(
        "name,action_rel,src_rel",
        COPIED_FILES,
        ids=[c[0] for c in COPIED_FILES],
    )
    def test_action_copy_matches_src_copy(self, name: str, action_rel: str, src_rel: str):
        action_path = REPO_ROOT / action_rel
        src_path = REPO_ROOT / src_rel

        assert action_path.exists(), f"action 副本缺失：{action_rel}"
        assert src_path.exists(), f"src 权威副本缺失：{src_rel}"

        action_bytes = action_path.read_bytes()
        src_bytes = src_path.read_bytes()
        assert action_bytes == src_bytes, (
            f"{name} 两份副本漂移：actions/branch-cleanup 与 src/infra_core/shell "
            f"必须字节一致。请双侧同步修改（action 自包含分发，src 是行为测试的"
            f"被测对象），经由 PR 评审。"
        )

    @pytest.mark.parametrize(
        "name,action_rel,src_rel",
        COPIED_FILES,
        ids=[c[0] for c in COPIED_FILES],
    )
    def test_action_copy_git_mode_matches_src(self, name: str, action_rel: str, src_rel: str):
        """git index 文件模式一致（脚本 100755 / 清单 100644）。

        composite action 按 git 原样检出文件；模式漂移会导致 action 内
        bash 调用行为差异或权限丢失。
        """
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "--stage", action_rel, src_rel],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        modes = {line.split()[3]: line.split()[0] for line in result.stdout.splitlines() if line}
        assert action_rel in modes, f"{action_rel} 未被 git 跟踪"
        assert src_rel in modes, f"{src_rel} 未被 git 跟踪"
        assert modes[action_rel] == modes[src_rel], (
            f"{name} git 模式漂移：{action_rel}={modes[action_rel]} vs "
            f"{src_rel}={modes[src_rel]}"
        )

    def test_action_yml_references_scripts_within_action_dir(self):
        """action.yml 引用的脚本必须位于 action 目录内（无路径穿越）。

        先例：test_naming_contract.py TestGovernanceActionScriptPath
        （M1 scrutiny 修复的 blocking 缺陷：`../` 越出 action 根在首次
        真实调用即 crash）。
        """
        action_yml = REPO_ROOT / "actions" / "branch-cleanup" / "action.yml"
        content = action_yml.read_text()

        run_blocks: list[str] = []
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("run:"):
                block: list[str] = []
                for cont in lines[i + 1 :]:
                    if cont.startswith("      ") or not cont.strip():
                        block.append(cont)
                    else:
                        break
                run_blocks.append("\n".join(block))

        assert run_blocks, "action.yml 必须包含 run 块"
        for block in run_blocks:
            assert "../" not in block, f"run 块包含路径穿越（../）：{block}"
        assert "$GITHUB_ACTION_PATH/branch_cleanup.sh" in content
        assert "$GITHUB_ACTION_PATH/branch_cleanup_issue.sh" in content
