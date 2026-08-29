"""INFRA-601: gh 调用显式仓库上下文守卫契约测试。

自建 runner 全局 .gitconfig 的 url.<镜像>.insteadOf 重写 github.com 后，gh 基于
workspace remote 的仓库推断误判 "no known GitHub host"（PR #1060 / INFRA-597
双 runner 实证；infra-core PR #49 修复了守卫脚本与 branch cleanup 的 4 处点位，
本测试锁定剩余 engine 点位的全量覆盖）。

契约：
- GITHUB_REPOSITORY env 注入时：所有依赖仓库解析的 gh 子命令（issue/pr/label/
  run 的 view/list/create/close/comment/edit/reopen）argv 必须包含
  --repo <GITHUB_REPOSITORY>
- env 未设置（本地调试）时：保持原命令形态（无 --repo 注入）
- 例外（结构性显式，无需 env 守卫）：
  - gh api（REST 路径已内嵌 owner/repo）
  - 已带显式 --repo 参数的调用（如 cross-repo pr view 的 URL 提取仓库）
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_engine_dir = Path(__file__).resolve().parent.parent / "src" / "infra_core" / "engine"
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))

import evolution_heartbeat  # noqa: E402
import evolution_utils  # noqa: E402


# ============================================================================
# gh_repo_args helper 契约
# ============================================================================
class TestGhRepoArgsHelper:
    """evolution_utils.gh_repo_args：env 注入 → ["--repo", ...]；未设置 → []。"""

    def test_returns_repo_pair_when_env_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        assert evolution_utils.gh_repo_args() == ["--repo", "hdot123-org/infra-core"]

    def test_returns_empty_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        assert evolution_utils.gh_repo_args() == []

    def test_whitespace_only_env_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "   ")
        assert evolution_utils.gh_repo_args() == []


def _gh_ok(stdout: str = "[]") -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _repo_of(argv: list[str]) -> str | None:
    """Extract the value of --repo from an argv list, or None."""
    try:
        idx = argv.index("--repo")
        return argv[idx + 1]
    except ValueError:
        return None


# ============================================================================
# evolution_utils: _close_issue / _issue_still_open / _fetch_issue_comments
# ============================================================================
class TestEvolutionUtilsGuards:
    def test_close_issue_injects_repo_when_env_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_utils.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_utils._close_issue(123, "RULE_1", "file.py")
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "close"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_close_issue_original_shape_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        with patch("evolution_utils.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_utils._close_issue(123, "RULE_1", "file.py")
        argv = mock_run.call_args[0][0]
        assert "--repo" not in argv

    def test_issue_still_open_injects_repo_when_env_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch(
            "evolution_utils.subprocess.run", return_value=_gh_ok('{"state": "OPEN"}')
        ) as mock_run:
            evolution_utils._issue_still_open(55)
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "view"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_fetch_issue_comments_injects_repo_when_env_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_utils.subprocess.run", return_value=_gh_ok("")) as mock_run:
            evolution_utils._fetch_issue_comments(77)
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "view"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_fetch_open_issues_injects_repo_when_env_set(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_utils.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_utils._fetch_open_issues("evolution-found")
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "list"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_check_merged_pr_env_fallback_when_no_repo_in_url(self, monkeypatch):
        """PR URL 无 owner/repo 提取 → GITHUB_REPOSITORY env 守卫兜底。"""
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        attachments = [{"url": "https://github.example-mirror.com/x/y/pull/9"}]
        with patch(
            "evolution_utils.subprocess.run", return_value=_gh_ok('{"mergedAt": "2026-01-01"}')
        ) as mock_run:
            result = evolution_utils._check_merged_pr(attachments, "INFRA-1")
        assert result is True
        argv = mock_run.call_args[0][0]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_check_merged_pr_url_repo_takes_priority(self, monkeypatch):
        """URL 提取的仓库优先（cross-repo 验证语义），不被 env 覆盖。"""
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        attachments = [{"url": "https://github.com/hdot123-org/memory/pull/9"}]
        with patch(
            "evolution_utils.subprocess.run", return_value=_gh_ok('{"mergedAt": "2026-01-01"}')
        ) as mock_run:
            result = evolution_utils._check_merged_pr(attachments, "INFRA-1")
        assert result is True
        argv = mock_run.call_args[0][0]
        assert _repo_of(argv) == "hdot123-org/memory"


# ============================================================================
# evolution_heartbeat: list/view/close/comment/create/run
# ============================================================================
class TestHeartbeatGuards:
    def test_check_pr_coverage_issue_list_injects_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_heartbeat.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_heartbeat.check_pr_coverage("evolution-found")
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "list"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_scanner_liveness_run_list_injects_repo(self, monkeypatch):
        import json as _json

        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        runs = _json.dumps([{"createdAt": "2026-08-29T00:00:00Z", "conclusion": "success"}])
        with patch("evolution_heartbeat.subprocess.run", return_value=_gh_ok(runs)) as mock_run:
            evolution_heartbeat.check_scanner_liveness(1.0)
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "run", "list"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_alert_issue_exists_injects_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_heartbeat.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_heartbeat.alert_issue_exists()
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "list"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_create_alert_issue_injects_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_heartbeat.subprocess.run", return_value=_gh_ok("url")) as mock_run:
            ok = evolution_heartbeat.create_alert_issue(scanner_stale=True, issues_without_pr=0)
        assert ok is True
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "create"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_list_open_alert_issues_injects_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "hdot123-org/infra-core")
        with patch("evolution_heartbeat.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_heartbeat.list_open_alert_issues()
        argv = mock_run.call_args[0][0]
        assert argv[:3] == ["gh", "issue", "list"]
        assert _repo_of(argv) == "hdot123-org/infra-core"

    def test_heartbeat_env_unset_keeps_original_shape(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        with patch("evolution_heartbeat.subprocess.run", return_value=_gh_ok()) as mock_run:
            evolution_heartbeat.check_pr_coverage("evolution-found")
        argv = mock_run.call_args[0][0]
        assert "--repo" not in argv


# ============================================================================
# Workflow 层：evolution 工作流的 gh label create 必须带显式仓库上下文
# （GITHUB_REPOSITORY 在 Actions 中恒注入，且 label 步骤的 || true 会掩盖
# 静默失败 → 无条件 --repo）
# ============================================================================
class TestWorkflowLabelGuards:
    _REPO_ROOT = Path(__file__).resolve().parent.parent

    @pytest.mark.parametrize(
        "workflow,expected_labels",
        [
            ("evolution-heartbeat.yml", ["evolution-heartbeat"]),
            ("evolution-scan.yml", ["evolution-found", "evolution-isolated"]),
        ],
    )
    def test_label_create_uses_repo_context(self, workflow: str, expected_labels: list[str]):
        content = (self._REPO_ROOT / ".github" / "workflows" / workflow).read_text()
        for label in expected_labels:
            assert f'gh --repo "$GITHUB_REPOSITORY" label create "{label}"' in content, (
                f"{workflow}: gh label create {label} 必须带 --repo "
                '"$GITHUB_REPOSITORY" 前缀（INFRA-601，免疫 runner insteadOf 重写）'
            )


# ============================================================================
# 静态全量覆盖：engine 源码中不允许出现未守卫的 gh 子命令调用形态
# （"gh" 后紧跟 issue/pr/label/run 子命令且同一 argv 构造内无 --repo）
# ============================================================================
class TestStaticCoverage:
    """遍历 engine 目录的 gh 调用点，确保每个依赖仓库解析的调用都有守卫。

    判定规则：源文件中每个以 "gh" 开头的 argv 构造（单行或列表字面量），
    若包含 issue/pr/label/run 子命令，则该构造内必须出现 --repo、
    *gh_repo_args() 或 --repo 前缀（gh --repo ...）三者之一。
    """

    _GH_SUBCOMMANDS = ("issue", "pr", "label", "run")

    @pytest.mark.parametrize(
        "rel",
        [
            "evolution_utils.py",
            "evolution_scanner.py",
            "evolution_heartbeat.py",
        ],
    )
    def test_no_unguarded_gh_calls(self, rel: str):
        src = (_engine_dir / rel).read_text()
        lines = src.splitlines()
        violations: list[str] = []

        # 每个 "gh" argv 构造：从 "gh" 行起向后取固定 12 行窗口（足够覆盖
        # 本仓所有 gh 列表字面量 + 后续 .extend/切片守卫行），在窗口内判定。
        # 守卫可出现在列表字面量内（--repo / *gh_repo_args()）或紧随其后的
        # 条件扩展行（gh_repo_args() / extend(["--repo", ...])）。
        for i, line in enumerate(lines):
            if '"gh"' not in line:
                continue
            # 变量赋值形式（gh_cmd = [...]): 条件守卫在随后的 if/else 行，
            # 不得按块级语句截断；直接调用形式（subprocess.run([...])）:
            # 窗口遇块级语句截断防跨构造误判。
            is_assignment = "=" in line and "[" in line and "subprocess" not in line
            window = 6 if is_assignment else 12
            block = lines[i : i + window]
            text = "\n".join(block)
            # 例外：gh api（REST 路径内嵌仓库）
            if '"api"' in text:
                continue
            if not is_assignment:
                for k in range(1, len(block)):
                    if (
                        block[k]
                        .lstrip()
                        .startswith(("def ", "if ", "for ", "while ", "try:", "class "))
                    ):
                        block = block[:k]
                        break
                text = "\n".join(block)
            has_repo = ("--repo" in text) or ("gh_repo_args()" in text) or ("REPO_NAME" in text)
            if not has_repo:
                violations.append(f"{rel}:{i + 1}: {line.strip()}")

        assert not violations, (
            "未守卫的 gh 子命令调用（缺 --repo / gh_repo_args / REPO_NAME）:\n"
            + "\n".join(violations)
        )
