"""治理自检测试（VAL-SCAF-006 判定表全覆盖 + dry-run CLI + action 等价性）"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from infra_core.governance import (
    DEFAULT_PROTECTED_PATTERNS,
    EXIT_DENY,
    check_governance,
)

pytestmark = [pytest.mark.security, pytest.mark.business_policy]


class TestCheckGovernance:
    """check_governance 判定表"""

    def test_non_owner_touching_protected_path_denied(self):
        v = check_governance(
            changed_files=[".evolution/config.yml"],
            pr_author="someone-else",
        )
        assert v.allowed is False
        assert v.touched_protected is True
        assert ".evolution/**" in v.matched_patterns

    def test_non_owner_editing_readme_allowed(self):
        v = check_governance(
            changed_files=["README.md", "docs/architecture.md"],
            pr_author="someone-else",
        )
        assert v.allowed is True
        assert v.touched_protected is False

    def test_owner_touching_protected_path_allowed(self):
        v = check_governance(
            changed_files=[".evolution/config.yml", ".github/workflows/ci.yml"],
            pr_author="hdot123",
        )
        assert v.allowed is True
        assert v.touched_protected is True

    def test_empty_author_fail_closed(self):
        v = check_governance(changed_files=["README.md"], pr_author="")
        assert v.allowed is False
        assert "fail-closed" in v.reason

    def test_empty_changed_files_allowed(self):
        v = check_governance(changed_files=[], pr_author="someone-else")
        assert v.allowed is True
        assert v.touched_protected is False

    def test_directory_entry_itself_matches(self):
        """目录条目本身（如路径恰为 `.evolution`）也算触碰受保护路径"""
        v = check_governance(changed_files=[".evolution"], pr_author="someone-else")
        assert v.allowed is False
        assert v.touched_protected is True

    def test_renamed_into_protected_path_detected(self):
        v = check_governance(
            changed_files=[".evolution/moved.yml"],
            pr_author="someone-else",
        )
        assert v.allowed is False

    def test_engine_source_protected(self):
        v = check_governance(
            changed_files=["src/infra_core/engine/evolution_scanner.py"],
            pr_author="someone-else",
        )
        assert v.allowed is False

    def test_webhook_scripts_protected(self):
        v = check_governance(
            changed_files=["webhook-scripts/MANIFEST.sh"],
            pr_author="someone-else",
        )
        assert v.allowed is False

    def test_workflows_dir_protected(self):
        v = check_governance(
            changed_files=[".github/workflows/ci.yml"],
            pr_author="someone-else",
        )
        assert v.allowed is False

    def test_unprotected_src_allowed_for_non_owner(self):
        """受保护模式只覆盖 engine 子树，packs/cli 等源码不拦"""
        v = check_governance(
            changed_files=["src/infra_core/cli.py", "src/infra_core/packs/__init__.py"],
            pr_author="someone-else",
        )
        assert v.allowed is True

    def test_custom_patterns_respected(self):
        v = check_governance(
            changed_files=["zone/thing.yml"],
            pr_author="someone-else",
            protected_patterns=["zone/**"],
        )
        assert v.allowed is False

    def test_mixed_changes_single_protected_denied(self):
        """非受保护 + 受保护混合变更：只要触碰受保护路径即拒绝非 owner"""
        v = check_governance(
            changed_files=["README.md", ".evolution/config.yml", "tests/test_x.py"],
            pr_author="someone-else",
        )
        assert v.allowed is False
        assert v.touched_files == (".evolution/config.yml",)


class TestGovernanceDryRunCli:
    """CLI dry-run（VAL-SCAF-006 证据 (b)：本地模拟三分支判定）"""

    def _run(self, *cli_args: str) -> subprocess.CompletedProcess[str]:
        # Subprocess must be able to import infra_core even when the package
        # is not pip-installed (source checkout): prepend src/ to PYTHONPATH.
        # In CI (pip install -e) this is redundant but harmless.
        env = dict(os.environ)
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        env["PYTHONPATH"] = (
            src_dir + os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else src_dir
        )
        return subprocess.run(
            [sys.executable, "-m", "infra_core.governance", *cli_args],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_dry_run_non_owner_protected_path_denied(self):
        result = self._run("--author", "someone-else", "--files", ".evolution/config.yml")
        assert result.returncode == EXIT_DENY
        assert "拒绝" in result.stdout or "只有" in result.stdout
        assert "Traceback" not in result.stderr

    def test_dry_run_non_owner_unprotected_allowed(self):
        result = self._run("--author", "someone-else", "--files", "README.md")
        assert result.returncode == 0
        assert "Traceback" not in result.stderr

    def test_dry_run_owner_protected_path_allowed(self):
        result = self._run("--author", "hdot123", "--files", ".evolution/config.yml")
        assert result.returncode == 0
        assert "Traceback" not in result.stderr

    def test_dry_run_files_from_stdin(self):
        env = dict(os.environ)
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        env["PYTHONPATH"] = (
            src_dir + os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else src_dir
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "infra_core.governance",
                "--author",
                "someone-else",
                "--files-from",
                "-",
            ],
            input=".github/workflows/ci.yml\nREADME.md\n",
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == EXIT_DENY

    def test_dry_run_custom_owner_and_patterns(self):
        result = self._run(
            "--author",
            "alice",
            "--owner",
            "alice",
            "--patterns",
            "zone/**",
            "--files",
            "zone/a.yml",
        )
        assert result.returncode == 0

    def test_default_patterns_match_contract(self):
        """默认受保护模式与 governance 契约一致"""
        assert DEFAULT_PROTECTED_PATTERNS == (
            ".evolution/**",
            ".github/workflows/**",
            "src/infra_core/engine/**",
            "webhook-scripts/**",
        )


class TestActionScriptEquivalence:
    """action 内嵌脚本与包内模块判定等价（消费仓在任意 base 使用 action，
    不能假设 infra-core 已安装，故 action 自带脚本；两者必须判定一致）"""

    ACTION_SCRIPT = (
        Path(__file__).resolve().parent.parent
        / "actions"
        / "governance-check"
        / "governance_check.py"
    )

    CASES = [
        # (changed_files, author, owner, patterns)
        ([".evolution/config.yml"], "someone-else", "hdot123", None),
        (["README.md", "docs/architecture.md"], "someone-else", "hdot123", None),
        ([".evolution/config.yml", ".github/workflows/ci.yml"], "hdot123", "hdot123", None),
        ([], "someone-else", "hdot123", None),
        (["README.md"], "", "hdot123", None),
        ([".evolution"], "someone-else", "hdot123", None),
        (["src/infra_core/engine/evolution_scanner.py"], "someone-else", "hdot123", None),
        (["webhook-scripts/MANIFEST.sh"], "someone-else", "hdot123", None),
        (["src/infra_core/cli.py"], "someone-else", "hdot123", None),
        (["zone/a.yml", "zone/b.yml"], "alice", "bob", ["zone/**"]),
        (["zone/a.yml"], "alice", "alice", ["zone/**"]),
    ]

    def _run_action_script(
        self,
        files: list[str],
        author: str,
        owner: str,
        patterns: list[str] | None,
    ):
        cmd = [sys.executable, str(self.ACTION_SCRIPT), "--author", author, "--owner", owner]
        if patterns is not None:
            cmd += ["--patterns", ",".join(patterns)]
        for f in files:
            cmd += ["--files", f]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_action_script_exists(self):
        assert self.ACTION_SCRIPT.exists()

    def test_equivalent_verdicts_on_decision_table(self):
        from infra_core.governance import check_governance as pkg_check

        for files, author, owner, patterns in self.CASES:
            pkg = pkg_check(
                changed_files=files,
                pr_author=author,
                owner_login=owner,
                protected_patterns=patterns or list(DEFAULT_PROTECTED_PATTERNS),
            )
            action = self._run_action_script(files, author, owner, patterns)
            assert action.returncode == (0 if pkg.allowed else 1), (
                f"判定不一致：files={files} author={author} owner={owner} "
                f"patterns={patterns} pkg.allowed={pkg.allowed} "
                f"action.exit={action.returncode} action.stderr={action.stderr}"
            )
            assert "Traceback" not in action.stderr, action.stderr

    def test_action_script_stdin_mode(self):
        result = subprocess.run(
            [
                sys.executable,
                str(self.ACTION_SCRIPT),
                "--author",
                "someone-else",
                "--files-from",
                "-",
            ],
            input=".evolution/config.yml\n",
            capture_output=True,
            text=True,
        )
        assert result.returncode == EXIT_DENY
