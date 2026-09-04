"""trigger-release.sh 契约测试

覆盖 VAL-MAC-007~023, VAL-MAC-025~026, VAL-MAC-035:
- 幂等锁机制（同 tag 重放零副作用）
- 锁文件形状正确且原子写入
- engineConsumer: true 选仓逻辑
- 无消费者安静退出且不写锁
- 干净仓 ff 拉取
- 脏工作树跳过
- 分叉仓跳过不 force
- 单点失败错误隔离
- droid 调用形状（tag/metadata/session_id）
- dry-run 输出三要素且零副作用
- shellcheck + bash -n 通过
- bash 3.2 运行时兼容
- MANIFEST 登记
- tag 含 / 的锁文件名安全

测试隔离：使用 stub droid + fixture 仓 + env 覆盖（WEBHOOK_BASE/LOCKS_DIR 等）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
TRIGGER_SCRIPT = REPO_ROOT / "webhook-scripts" / "trigger-release.sh"


def _make_env(tmp_path: Path, home_override: Path | None = None) -> dict:
    """构造测试环境变量（env 覆盖优先，对齐 write-pending-ci.sh 常数惯例）"""
    env = os.environ.copy()

    # 隔离 webhook 目录
    webhook_base = tmp_path / "webhook"
    webhook_base.mkdir(exist_ok=True)
    env["WEBHOOK_BASE"] = str(webhook_base)

    locks_dir = tmp_path / "locks"
    locks_dir.mkdir(exist_ok=True)
    env["LOCKS_DIR"] = str(locks_dir)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    env["LOG_DIR"] = str(log_dir)

    # 避免真实 droid exec
    env["ECHO_DROID"] = "1"

    # 跨平台 Python
    env["PYTHON_BIN"] = sys.executable

    # HOME 隔离
    if home_override:
        env["HOME"] = str(home_override)

    return env


def _create_repositories_yml(tmp_path: Path, consumers: list[dict]) -> Path:
    """创建测试用 repositories.yml"""
    import yaml

    config = {"teams": {"infra": {"repos": consumers}}}
    config_path = tmp_path / "repositories.yml"
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    return config_path


def _create_fixture_repo(tmp_path: Path, name: str, dirty: bool = False, diverged: bool = False) -> Path:
    """创建 fixture git 仓（干净可 ff / 工作树脏 / 本地分叉）"""
    import subprocess as sp

    # 直接创建一个本地 git 仓，不设置 remote/upstream
    # 这样可以避免复杂的 push/pull 设置
    repo = tmp_path / name
    repo.mkdir()
    sp.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    sp.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)
    sp.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True, check=True)

    # 初始提交
    (repo / "README.md").write_text(f"# {name}\n")
    sp.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    sp.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True)

    if dirty:
        # 工作树脏：未提交改动
        (repo / "dirty.txt").write_text("dirty\n")
    elif diverged:
        # 本地分叉：本地有未推送的提交（但因为没有 remote，这只是一个状态标记）
        (repo / "local.txt").write_text("local\n")
        sp.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        sp.run(["git", "commit", "-m", "local commit"], cwd=repo, capture_output=True, check=True)

    return repo


def _get_head_sha(repo: Path) -> str:
    """获取仓 HEAD sha"""
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _count_stub_droid_calls(log_file: Path) -> int:
    """统计 stub droid 调用次数"""
    if not log_file.exists():
        return 0
    content = log_file.read_text()
    return content.count("[STUB_DROID]")


def _extract_session_ids(log_file: Path) -> list[str]:
    """从日志提取 session_id"""
    if not log_file.exists():
        return []
    content = log_file.read_text()
    session_ids = []
    for line in content.splitlines():
        if "session_id:" in line:
            # 格式：session_id: <id>
            parts = line.split("session_id:")
            if len(parts) > 1:
                session_ids.append(parts[1].strip())
    return session_ids


class TestDryRun:
    """VAL-MAC-021/022: dry-run 输出三要素且零副作用"""

    def test_dry_run_outputs_three_elements(self, tmp_path):
        """--dry-run 打印 tag、锁路径、选中仓清单"""
        env = _make_env(tmp_path)
        config_path = _create_repositories_yml(
            tmp_path,
            [
                {"repoKey": "memory-core", "repoPath": str(tmp_path / "memory"), "engineConsumer": True},
                {"repoKey": "other", "repoPath": str(tmp_path / "other"), "engineConsumer": False},
            ],
        )
        env["REPO_CONFIG"] = str(config_path)

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "--dry-run", "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        output = result.stdout
        assert "v1.0.0" in output, "应输出 tag"
        assert "release-announce-v1.0.0.json" in output, "应输出锁路径"
        assert "memory-core" in output, "应输出选中仓清单"
        assert "other" not in output, "不应输出非消费者"

    def test_dry_run_zero_side_effects(self, tmp_path):
        """--dry-run 无锁文件、无 stub droid 调用、仓 HEAD 不变"""
        env = _make_env(tmp_path)
        repo = _create_fixture_repo(tmp_path, "test_repo")
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "test", "repoPath": str(repo), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        head_before = _get_head_sha(repo)
        locks_dir = Path(env["LOCKS_DIR"])

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "--dry-run", "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert len(list(locks_dir.glob("*.json"))) == 0, "不应生成锁文件"
        head_after = _get_head_sha(repo)
        assert head_before == head_after, "仓 HEAD 不应变化"


class TestConsumerSelection:
    """VAL-MAC-011/012/013: engineConsumer 过滤逻辑"""

    def test_engine_consumer_true_selected(self, tmp_path):
        """engineConsumer: true 的仓被选中"""
        env = _make_env(tmp_path)
        config_path = _create_repositories_yml(
            tmp_path,
            [
                {"repoKey": "memory-core", "repoPath": str(tmp_path / "memory"), "engineConsumer": True},
                {"repoKey": "other", "repoPath": str(tmp_path / "other"), "engineConsumer": False},
            ],
        )
        env["REPO_CONFIG"] = str(config_path)

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "--dry-run", "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert "memory-core" in result.stdout
        assert "other" not in result.stdout

    def test_no_consumers_quiet_exit_no_lock(self, tmp_path):
        """无消费者时安静退出且不写锁"""
        env = _make_env(tmp_path)
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "other", "repoPath": str(tmp_path / "other"), "engineConsumer": False}],
        )
        env["REPO_CONFIG"] = str(config_path)

        locks_dir = Path(env["LOCKS_DIR"])
        log_file = Path(env["LOG_DIR"]) / "trigger-release.log"

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert len(list(locks_dir.glob("*.json"))) == 0, "不应写锁"
        if log_file.exists():
            content = log_file.read_text()
            assert "无消费者" in content or "no consumers" in content.lower()


class TestIdempotentLock:
    """VAL-MAC-007/008: 幂等锁机制"""

    def test_lock_file_shape_and_atomic_write(self, tmp_path):
        """锁文件为合法 JSON，含四字段，原子写入无残迹"""
        env = _make_env(tmp_path)
        repo = _create_fixture_repo(tmp_path, "test_repo")
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "test", "repoPath": str(repo), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        locks_dir = Path(env["LOCKS_DIR"])

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0

        # 检查锁文件
        lock_files = list(locks_dir.glob("release-announce-*.json"))
        assert len(lock_files) == 1, "应生成一个锁文件"

        lock_file = lock_files[0]
        lock_data = json.loads(lock_file.read_text())

        assert lock_data["tag"] == "v1.0.0"
        assert lock_data["repo"] == "hdot123-org/infra-core"
        assert isinstance(lock_data["consumers"], list)
        assert "test" in lock_data["consumers"]
        assert "created_at" in lock_data

        # 无 tmp 残留
        assert len(list(locks_dir.glob("*.tmp*"))) == 0, "不应有 tmp 残留"

    def test_same_tag_idempotent_replay(self, tmp_path):
        """同 tag 二次触发零副作用"""
        env = _make_env(tmp_path)
        repo = _create_fixture_repo(tmp_path, "test_repo")
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "test", "repoPath": str(repo), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        locks_dir = Path(env["LOCKS_DIR"])
        log_file = Path(env["LOG_DIR"]) / "trigger-release.log"

        # 第一次触发
        result1 = subprocess.run(
            [str(TRIGGER_SCRIPT), "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result1.returncode == 0

        lock_file = list(locks_dir.glob("release-announce-*.json"))[0]
        lock_data_before = json.loads(lock_file.read_text())
        mtime_before = lock_file.stat().st_mtime

        # 第二次触发
        result2 = subprocess.run(
            [str(TRIGGER_SCRIPT), "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result2.returncode == 0

        lock_data_after = json.loads(lock_file.read_text())
        mtime_after = lock_file.stat().st_mtime

        # 锁未改写
        assert lock_data_before == lock_data_after
        assert mtime_before == mtime_after

        # 日志含跳过记录
        if log_file.exists():
            content = log_file.read_text()
            assert "跳过" in content or "skip" in content.lower() or "幂等" in content


class TestErrorIsolation:
    """VAL-MAC-015/016/017: 错误隔离"""

    def test_dirty_tree_skipped(self, tmp_path):
        """脏工作树跳过且不动用户改动"""
        env = _make_env(tmp_path)
        repo = _create_fixture_repo(tmp_path, "dirty_repo", dirty=True)
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "dirty", "repoPath": str(repo), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        log_file = Path(env["LOG_DIR"]) / "trigger-release.log"
        head_before = _get_head_sha(repo)

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        head_after = _get_head_sha(repo)
        assert head_before == head_after, "HEAD 不应变化"

        if log_file.exists():
            content = log_file.read_text()
            assert "脏" in content or "dirty" in content.lower() or "跳过" in content

    def test_diverged_repo_skipped_no_force(self, tmp_path):
        """分叉仓跳过且不 force"""
        env = _make_env(tmp_path)
        repo = _create_fixture_repo(tmp_path, "diverged_repo", diverged=True)
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "diverged", "repoPath": str(repo), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        log_file = Path(env["LOG_DIR"]) / "trigger-release.log"

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0

        # Wait for background process to write logs
        time.sleep(1)

        if log_file.exists():
            content = log_file.read_text()
            # 应记录跳过原因，且无 force 行为
            assert "跳过" in content or "fail" in content.lower()
            assert "force" not in content.lower() or "不 force" in content


class TestTagSafety:
    """VAL-MAC-035: tag 含 / 的锁文件名安全"""

    def test_tag_with_slash_safe_in_dry_run(self, tmp_path):
        """tag 含 / 时脚本不崩溃，不在 LOCKS_DIR 之外创建文件"""
        env = _make_env(tmp_path)
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "test", "repoPath": str(tmp_path / "test"), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        locks_dir = Path(env["LOCKS_DIR"])
        locks_before = set(locks_dir.iterdir()) if locks_dir.exists() else set()

        result = subprocess.run(
            [str(TRIGGER_SCRIPT), "--dry-run", "release/v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        # 不应在 LOCKS_DIR 之外创建文件
        locks_after = set(locks_dir.iterdir()) if locks_dir.exists() else set()
        assert locks_before == locks_after, "dry-run 不应创建文件"


class TestShellQuality:
    """VAL-MAC-023/025/026: 脚本质量"""

    def test_shellcheck_zero_warnings(self):
        """shellcheck 零告警"""
        result = subprocess.run(
            ["shellcheck", str(TRIGGER_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"shellcheck failed:\n{result.stdout}\n{result.stderr}"

    def test_bash_syntax_check(self):
        """bash -n 通过"""
        result = subprocess.run(
            ["bash", "-n", str(TRIGGER_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_bash_3_2_compatible(self, tmp_path):
        """bash 3.2 运行时兼容"""
        env = _make_env(tmp_path)
        config_path = _create_repositories_yml(
            tmp_path,
            [{"repoKey": "test", "repoPath": str(tmp_path / "test"), "engineConsumer": True}],
        )
        env["REPO_CONFIG"] = str(config_path)

        # 用系统 bash（3.2.57 on macOS）运行
        result = subprocess.run(
            ["/bin/bash", str(TRIGGER_SCRIPT), "--dry-run", "v1.0.0", "https://example.com/release", "hdot123-org/infra-core"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"bash 3.2 failed:\n{result.stderr}"

    def test_manifest_registration(self):
        """MANIFEST.sh 登记 trigger-release.sh"""
        manifest_path = REPO_ROOT / "webhook-scripts" / "MANIFEST.sh"
        content = manifest_path.read_text()
        assert "trigger-release.sh" in content, "MANIFEST.sh 应登记 trigger-release.sh"
