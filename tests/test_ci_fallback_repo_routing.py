"""INFRA-701: CI fallback repo 路由回归测试

事故背景（2026-09-01，infra-core PR #136）：hooks.json 的 ci-complete 钩子只
透传 4 个参数（pr_number/branch/sha/status），CI payload 的 repo 字段被丢弃。
release-please PR #136 的 pending-ci 文件不存在（非 session 会话创建，无
write-pending-ci 注册），fallback 走 missing-pending-ci 路径，repo 选择退化为
webhook 接收器的 command-working-directory（/Users/busiji/memory）——infra-core
的 PR #136 被误派到 memory 仓上下文（memory 仓 2026-07 的旧 PR #136）。

修复语义（fallback repo 选择优先级）：
1. PENDING_CWD —— pending-ci 文件携带的 cwd（发 PR 会话的确切仓库路径）
2. 显式 repo slug（CI payload repo 字段 → repositories.yml 反查本地路径）
3. SCRIPT_CWD —— webhook 接收器工作目录（最后兜底）

测试隔离：ECHO_DROID=1 避免真实 droid exec；WEBHOOK_BASE/LOCK_DIR/LOG_DIR
指向临时目录；不读写生产 ~/.factory/webhook。FACTORY_TOKEN 用动态拼接的假值
（FACTORY_API_BASE 指向闭端口，不会真注入）；FLOCK_BIN 按平台解析——脚本默认
路径 /opt/homebrew/bin/flock 仅 macOS 存在，Linux CI 上 flock 缺失（退出码 127）
会被幂等锁分支误判为 ci_lock_held，导致 fallback 未派生（INFRA-701 CI 首红根因）。
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
TRIGGER_SCRIPT = REPO_ROOT / "webhook-scripts" / "trigger-ci-droid.sh"


def _make_env(tmp_path: Path, repo_config: Path | None = None) -> dict:
    """构造测试环境变量（全部隔离到临时目录）"""
    env = os.environ.copy()

    webhook_base = tmp_path / "webhook"
    webhook_base.mkdir(exist_ok=True)
    env["WEBHOOK_BASE"] = str(webhook_base)

    locks_dir = tmp_path / "locks"
    locks_dir.mkdir(exist_ok=True)
    env["LOCK_DIR"] = str(locks_dir)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    env["LOG_DIR"] = str(log_dir)

    # 闭端口：注入路径必失败，强制走 fallback 分支
    env["FACTORY_API_BASE"] = "http://127.0.0.1:1"

    # 测试用 Factory token（动态拼接假值，仅满足脚本 ^fk- 前缀校验；闭端口不会真注入）。
    # 不设假值时脚本会走 1Password 读取（op-mcp.sh），非 macOS 环境必然失败并在
    # fallback 派生前 exit 0。禁止在源码中出现完整 token 字面量（Droid-Shield 密钥检测）。
    env["FACTORY_TOKEN"] = "fk-" + "test-stub-" + "not-real"

    # 跨平台 flock 路径（对齐 tests/test_trigger_ci_droid_fallback.py 的 temp_env）：
    # 脚本默认 /opt/homebrew/bin/flock 仅 macOS 存在
    flock_path = shutil.which("flock")
    if flock_path:
        env["FLOCK_BIN"] = flock_path

    env["ECHO_DROID"] = "1"
    env["POSTHOG_DRY_RUN"] = "1"
    env["PYTHON_BIN"] = sys.executable

    if repo_config is not None:
        env["REPO_CONFIG"] = str(repo_config)
    else:
        # 未提供测试配置时指向不存在的路径，切断对生产 repositories.yml 的依赖
        # （slug 解析必然失败，走 SCRIPT_CWD 兜底，行为确定）
        env["REPO_CONFIG"] = str(tmp_path / "repositories.yml.absent")

    # 剥离宿主机 CI_REPO（本仓库 CI 会话环境携带 CI_REPO=hdot123-org/infra-core，
    # 会经 REPO_SLUG_ARG 的 ${CI_REPO:-} 兜底渗入 legacy 调用测试；需要 CI_REPO
    # 的用例在 _make_env 之后显式设置）
    env.pop("CI_REPO", None)

    return env


def _make_repo_config(tmp_path: Path, entries: list[dict]) -> Path:
    """生成测试用 repositories.yml（结构对齐生产配置）"""
    config = {
        "version": 1,
        "teams": {
            "infra": {
                "teamKey": "INFRA",
                "repos": entries,
            }
        },
    }
    config_path = tmp_path / "repositories.yml"
    config_path.write_text(yaml.dump(config))
    return config_path


def _read_latest_log(temp_env: dict) -> str:
    """读取脚本写入的最新日志文件内容（LOG_DIR 由脚本从 WEBHOOK_BASE 派生）"""
    webhook_base = Path(temp_env["WEBHOOK_BASE"])
    log_dir = webhook_base / "logs"
    log_files = sorted(log_dir.glob("*.log"))
    if not log_files:
        return ""
    return log_files[-1].read_text()


def _create_pending_file(locks_dir: Path, pr_number: int, cwd: str | None = None) -> Path:
    """创建 pending-ci 测试文件（M5 schema）"""
    data = {
        "pr_number": str(pr_number),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if cwd is not None:
        data["cwd"] = cwd
    file_path = locks_dir / f"pending-ci-{pr_number}.json"
    file_path.write_text(json.dumps(data))
    return file_path


class TestFallbackRepoRouting:
    """INFRA-701: fallback repo 三级优先级路由"""

    def test_missing_pending_ci_routes_by_repo_slug(self, tmp_path):
        """missing-pending-ci 路径：第 5 参数 repo slug 经 repositories.yml 反查本地路径

        复现 #136 事故形态（无 pending 文件），验证 repo 参数不再退化为
        SCRIPT_CWD（事故中为 memory 仓）。
        """
        target_repo = tmp_path / "infra-core-like"
        target_repo.mkdir()
        repo_config = _make_repo_config(
            tmp_path,
            [
                {
                    "repoKey": "infra-core",
                    "repoPath": str(target_repo),
                    "githubRepo": "acme/infra-core",
                }
            ],
        )
        env = _make_env(tmp_path, repo_config)

        result = subprocess.run(
            [
                "bash",
                str(TRIGGER_SCRIPT),
                "136",  # 事故 PR 号
                "release-please--branches--main",
                "abc123",
                "success",
                "acme/infra-core",  # 第 5 参数：repo slug
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        log_content = _read_latest_log(env)
        combined = result.stdout + result.stderr + log_content

        # fallback 被派生
        assert "FALLBACK: Spawning droid exec" in combined, "Expected fallback spawn"
        # 路由到 slug 解析的本地路径，而非脚本 CWD
        assert f"FALLBACK: Spawning droid exec for PR #136 (repo: {target_repo})" in combined, (
            f"Expected fallback repo {target_repo}, got:\n{combined[-800:]}"
        )
        # 显式路由日志
        assert "routed by CI payload repo slug" in combined

    def test_missing_pending_ci_ci_repo_env_fallback(self, tmp_path):
        """第 5 参数缺省时 CI_REPO 环境变量兜底（hooks.json 双通道的 env 通道）"""
        target_repo = tmp_path / "via-env"
        target_repo.mkdir()
        repo_config = _make_repo_config(
            tmp_path,
            [{"repoKey": "via-env", "repoPath": str(target_repo), "githubRepo": "acme/via-env"}],
        )
        env = _make_env(tmp_path, repo_config)
        env["CI_REPO"] = "acme/via-env"

        result = subprocess.run(
            ["bash", str(TRIGGER_SCRIPT), "200", "b", "abc", "success"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        log_content = _read_latest_log(env)
        combined = result.stdout + result.stderr + log_content

        assert "FALLBACK: Spawning droid exec" in combined
        assert f"(repo: {target_repo})" in combined, (
            f"Expected env-channel routing to {target_repo}, got:\n{combined[-800:]}"
        )

    def test_pending_cwd_wins_over_repo_slug(self, tmp_path):
        """pending-ci 文件存在且带 cwd：PENDING_CWD 优先于 repo slug（最权威）"""
        target_repo = tmp_path / "slug-target"
        target_repo.mkdir()
        pending_cwd = tmp_path / "pending-cwd-target"
        pending_cwd.mkdir()
        repo_config = _make_repo_config(
            tmp_path,
            [
                {
                    "repoKey": "slug-target",
                    "repoPath": str(target_repo),
                    "githubRepo": "acme/slug-target",
                }
            ],
        )
        env = _make_env(tmp_path, repo_config)

        locks_dir = Path(env["LOCK_DIR"])
        _create_pending_file(locks_dir, 201, cwd=str(pending_cwd))

        result = subprocess.run(
            ["bash", str(TRIGGER_SCRIPT), "201", "b", "abc", "passed", "acme/slug-target"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        log_content = _read_latest_log(env)
        combined = result.stdout + result.stderr + log_content

        assert "FALLBACK: Spawning droid exec" in combined
        assert f"(repo: {pending_cwd})" in combined, (
            f"PENDING_CWD should win over slug; got:\n{combined[-800:]}"
        )

    def test_unresolvable_slug_falls_back_to_script_cwd(self, tmp_path):
        """repo slug 无法解析（不在 repositories.yml）→ 回退 SCRIPT_CWD 并留 WARN"""
        repo_config = _make_repo_config(
            tmp_path,
            [{"repoKey": "known", "repoPath": str(tmp_path / "known"), "githubRepo": "acme/known"}],
        )
        env = _make_env(tmp_path, repo_config)

        script_cwd = tmp_path / "receiver-cwd"
        script_cwd.mkdir()

        result = subprocess.run(
            ["bash", str(TRIGGER_SCRIPT), "202", "b", "abc", "success", "unknown-org/unknown-repo"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=script_cwd,
        )

        log_content = _read_latest_log(env)
        combined = result.stdout + result.stderr + log_content

        assert "FALLBACK: Spawning droid exec" in combined
        assert "not resolvable" in combined, "Expected WARN for unresolvable slug"
        assert f"(repo: {script_cwd})" in combined, (
            f"Expected SCRIPT_CWD fallback, got:\n{combined[-800:]}"
        )

    def test_legacy_call_without_repo_keeps_script_cwd(self, tmp_path):
        """旧调用形态（4 参数、无 CI_REPO）：保持 SCRIPT_CWD 行为，向后兼容"""
        env = _make_env(tmp_path)

        script_cwd = tmp_path / "legacy-cwd"
        script_cwd.mkdir()

        result = subprocess.run(
            ["bash", str(TRIGGER_SCRIPT), "203", "b", "abc", "success"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=script_cwd,
        )

        log_content = _read_latest_log(env)
        combined = result.stdout + result.stderr + log_content

        assert "FALLBACK: Spawning droid exec" in combined
        assert f"(repo: {script_cwd})" in combined, (
            f"Legacy call should keep SCRIPT_CWD, got:\n{combined[-800:]}"
        )

    def test_startup_log_includes_repo_field(self, tmp_path):
        """启动日志记录 repo 字段（可观测性：payload repo 不再静默丢弃）"""
        env = _make_env(tmp_path)

        subprocess.run(
            ["bash", str(TRIGGER_SCRIPT), "204", "b", "abc", "success", "acme/some-repo"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        log_content = _read_latest_log(env)
        assert "REPO=acme/some-repo" in log_content, (
            f"Startup log should include repo field, got:\n{log_content[:500]}"
        )

    def test_resolved_path_must_exist(self, tmp_path):
        """slug 命中但本地路径不存在 → 不采用，回退 SCRIPT_CWD（防幽灵路径）"""
        repo_config = _make_repo_config(
            tmp_path,
            [
                {
                    "repoKey": "ghost",
                    "repoPath": str(tmp_path / "does-not-exist"),
                    "githubRepo": "acme/ghost",
                }
            ],
        )
        env = _make_env(tmp_path, repo_config)

        script_cwd = tmp_path / "real-cwd"
        script_cwd.mkdir()

        result = subprocess.run(
            ["bash", str(TRIGGER_SCRIPT), "205", "b", "abc", "success", "acme/ghost"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=script_cwd,
        )

        log_content = _read_latest_log(env)
        combined = result.stdout + result.stderr + log_content

        assert "FALLBACK: Spawning droid exec" in combined
        assert f"(repo: {script_cwd})" in combined, (
            f"Non-existent resolved path must fall back to SCRIPT_CWD, got:\n{combined[-800:]}"
        )


class TestHooksConfigContract:
    """生产 hooks.json 契约：ci-complete 钩子透传 repo 字段

    hooks.json 不在 MANIFEST 管控内（生产专属配置），本契约测试防回退：
    repo 字段一旦从 hooks.json 丢失，INFRA-701 的参数通道即断裂。
    """

    def test_ci_complete_hook_passes_repo_argument(self):
        hooks_path = Path.home() / ".factory" / "webhook" / "hooks.json"
        if not hooks_path.exists():
            import pytest

            pytest.skip("生产 hooks.json 不存在（非 Mac 生产环境）")

        hooks = json.loads(hooks_path.read_text())
        ci_hook = next((h for h in hooks if h.get("id") == "ci-complete"), None)
        assert ci_hook is not None, "ci-complete hook must exist"

        arg_names = [a.get("name") for a in ci_hook.get("pass-arguments-to-command", [])]
        assert arg_names[:4] == ["pr_number", "branch", "sha", "status"]
        assert "repo" in arg_names, (
            "ci-complete hook must pass payload repo as the 5th argument (INFRA-701)"
        )

        env_names = [e.get("envname") for e in ci_hook.get("pass-environment-to-command", [])]
        assert "CI_REPO" in env_names, (
            "ci-complete hook must pass payload repo as CI_REPO env (INFRA-701)"
        )


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
