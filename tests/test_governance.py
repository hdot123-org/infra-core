"""治理自检测试（VAL-SCAF-006 判定表全覆盖 + dry-run CLI）"""

import subprocess
import sys

from infra_core.governance import (
    DEFAULT_PROTECTED_PATTERNS,
    EXIT_DENY,
    check_governance,
)


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
        return subprocess.run(
            [sys.executable, "-m", "infra_core.governance", *cli_args],
            capture_output=True,
            text=True,
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
