"""poll-releases.sh 契约测试 (VAL-ANN-029)

覆盖：
- 锁存在 → 跳过
- 锁不存在 → 调用 trigger-release.sh
- --init 自举：为全部现存 tag 预建锁（API 失败/解析失败 exit 非零）
- API 容错：正常模式失败/超时 → 日志留痕 + exit 0
- 列表式轮询：latest 与非 latest 一视同仁
- 哨兵机制：无 .poll-bootstrap-done 禁绝派发；--init 成功后落哨兵
- PYTHON_BIN 惯例（对齐 trigger-release.sh）

测试策略：stub gh api + stub trigger-release.sh，验证行为分支。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "webhook-scripts" / "poll-releases.sh"


def _make_env(tmp_path: Path, with_sentinel: bool = False) -> dict[str, str]:
    """构造测试环境变量（隔离 webhook 目录）

    Args:
        tmp_path: pytest 临时目录
        with_sentinel: 是否创建 .poll-bootstrap-done 哨兵文件
    """
    webhook_base = tmp_path / "webhook"
    webhook_base.mkdir(exist_ok=True)
    locks_dir = webhook_base / "locks"
    locks_dir.mkdir(exist_ok=True)
    logs_dir = webhook_base / "logs"
    logs_dir.mkdir(exist_ok=True)

    # 哨兵文件（正常模式需要）
    if with_sentinel:
        sentinel = locks_dir / ".poll-bootstrap-done"
        sentinel.touch()

    return {
        "WEBHOOK_BASE": str(webhook_base),
        "LOCKS_DIR": str(locks_dir),
        "LOG_DIR": str(logs_dir),
        "PATH": str(tmp_path) + ":" + "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PYTHON_BIN": sys.executable,
    }


def _create_stub_gh(tmp_path: Path, releases: list[dict[str, Any]]) -> Path:
    """创建 stub gh 脚本，返回固定 JSON"""
    stub_path = tmp_path / "gh"
    json_output = json.dumps(releases)
    stub_script = f"""#!/bin/bash
# Stub gh: 返回固定 releases JSON
cat <<'EOF'
{json_output}
EOF
"""
    stub_path.write_text(stub_script)
    stub_path.chmod(0o755)
    return stub_path


def _create_stub_trigger(tmp_path: Path, capture_file: Path) -> Path:
    """创建 stub trigger-release.sh，记录调用参数"""
    stub_path = tmp_path / "trigger-release.sh"
    stub_script = f"""#!/bin/bash
# Stub trigger-release.sh: 记录调用参数
echo "$1|$2|$3" >> "{capture_file}"
"""
    stub_path.write_text(stub_script)
    stub_path.chmod(0o755)
    return stub_path


class TestPollReleasesLockExists:
    """VAL-ANN-029: 锁存在 → 跳过"""

    def test_lock_exists_skips_tag(self, tmp_path):
        """tag 已有锁时，不调用 trigger-release.sh"""
        env = _make_env(tmp_path, with_sentinel=True)
        locks_dir = Path(env["LOCKS_DIR"])

        # 预建锁
        lock_file = locks_dir / "release-announce-v1.0.0.json"
        lock_file.write_text(
            json.dumps(
                {
                    "tag": "v1.0.0",
                    "repo": "hdot123-org/infra-core",
                    "consumers": ["memory-core"],
                    "created_at": "2026-09-05T00:00:00Z",
                }
            )
        )

        # 创建 stub gh（返回一个 release）
        releases = [
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.0.0",
            }
        ]
        _create_stub_gh(tmp_path, releases)

        # 创建 stub trigger（不应被调用）
        capture_file = tmp_path / "trigger_calls.log"
        _create_stub_trigger(tmp_path, capture_file)

        env["TRIGGER_SCRIPT"] = str(tmp_path / "trigger-release.sh")

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"脚本应成功退出：{result.stderr}"

        # trigger 不应被调用
        if capture_file.exists():
            calls = capture_file.read_text().strip()
            assert calls == "", f"锁已存在时不应调用 trigger，实际调用：{calls}"

        # 日志应记录跳过
        log_file = Path(env["LOG_DIR"]) / "poll-releases.log"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "锁已存在" in log_content or "跳过" in log_content


class TestPollReleasesLockNotExists:
    """VAL-ANN-029: 锁不存在 → 调用 trigger-release.sh"""

    def test_lock_not_exists_calls_trigger(self, tmp_path):
        """tag 无锁时，调用 trigger-release.sh"""
        env = _make_env(tmp_path, with_sentinel=True)

        # 创建 stub gh（返回一个 release）
        releases = [
            {
                "tag_name": "v2.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v2.0.0",
            }
        ]
        _create_stub_gh(tmp_path, releases)

        # 创建 stub trigger（应被调用）
        capture_file = tmp_path / "trigger_calls.log"
        _create_stub_trigger(tmp_path, capture_file)

        env["TRIGGER_SCRIPT"] = str(tmp_path / "trigger-release.sh")

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"脚本应成功退出：{result.stderr}"

        # trigger 应被调用
        assert capture_file.exists(), "trigger 应被调用"
        calls = capture_file.read_text().strip()
        assert calls != "", "应至少调用一次 trigger"

        # 验证调用参数
        lines = calls.split("\n")
        assert len(lines) == 1, f"应恰好调用一次，实际 {len(lines)} 次"
        tag, url, repo = lines[0].split("|")
        assert tag == "v2.0.0"
        assert "v2.0.0" in url
        assert repo == "hdot123-org/infra-core"


class TestPollReleasesInit:
    """VAL-ANN-029: --init 自举"""

    def test_init_bootstraps_all_existing_tags(self, tmp_path):
        """--init 为全部现存 tag 预建锁"""
        env = _make_env(tmp_path)
        locks_dir = Path(env["LOCKS_DIR"])

        # 创建 stub gh（返回多个 release）
        releases = [
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.0.0",
            },
            {
                "tag_name": "v0.9.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v0.9.0",
            },
            {
                "tag_name": "v0.8.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v0.8.0",
            },
        ]
        _create_stub_gh(tmp_path, releases)

        result = subprocess.run(
            [str(SCRIPT_PATH), "--init"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"--init 应成功退出：{result.stderr}"

        # 应创建三个锁
        lock_files = list(locks_dir.glob("release-announce-*.json"))
        assert len(lock_files) == 3, f"应创建 3 个锁，实际 {len(lock_files)} 个"

        # 验证锁内容
        for lock_file in lock_files:
            lock_data = json.loads(lock_file.read_text())
            assert "tag" in lock_data
            assert lock_data["repo"] == "hdot123-org/infra-core"
            assert lock_data.get("bootstrap") is True, "--init 创建的锁应含 bootstrap: true"

        # --init 成功后应落哨兵
        sentinel = locks_dir / ".poll-bootstrap-done"
        assert sentinel.exists(), "--init 成功后应落哨兵 .poll-bootstrap-done"

    def test_init_skips_existing_locks(self, tmp_path):
        """--init 跳过已存在锁的 tag"""
        env = _make_env(tmp_path)
        locks_dir = Path(env["LOCKS_DIR"])

        # 预建一个锁
        existing_lock = locks_dir / "release-announce-v1.0.0.json"
        existing_lock.write_text(
            json.dumps(
                {
                    "tag": "v1.0.0",
                    "repo": "hdot123-org/infra-core",
                    "consumers": ["memory-core"],
                    "created_at": "2026-09-05T00:00:00Z",
                }
            )
        )
        existing_mtime = existing_lock.stat().st_mtime

        # 创建 stub gh（返回多个 release，含已锁的 tag）
        releases = [
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.0.0",
            },
            {
                "tag_name": "v0.9.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v0.9.0",
            },
        ]
        _create_stub_gh(tmp_path, releases)

        result = subprocess.run(
            [str(SCRIPT_PATH), "--init"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0

        # v1.0.0 的锁不应被改写
        assert existing_lock.stat().st_mtime == existing_mtime, "已存在锁不应被改写"

        # v0.9.0 应新建锁
        new_lock = locks_dir / "release-announce-v0.9.0.json"
        assert new_lock.exists(), "应为新 tag 创建锁"

    def test_init_api_failure_exits_nonzero(self, tmp_path):
        """--init API 调用失败时应 exit 非零（禁静默半自举）"""
        env = _make_env(tmp_path)
        locks_dir = Path(env["LOCKS_DIR"])

        # 创建会失败的 stub gh
        stub_gh = tmp_path / "gh"
        stub_gh.write_text("#!/bin/bash\necho 'API error' >&2\nexit 1\n")
        stub_gh.chmod(0o755)

        result = subprocess.run(
            [str(SCRIPT_PATH), "--init"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode != 0, "--init API 失败时应 exit 非零（禁静默半自举）"

        # 不应落哨兵
        sentinel = locks_dir / ".poll-bootstrap-done"
        assert not sentinel.exists(), "API 失败时不应落哨兵"

        # 应记录错误日志
        log_file = Path(env["LOG_DIR"]) / "poll-releases.log"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "ERROR" in log_content or "失败" in log_content


class TestPollReleasesAPIError:
    """VAL-ANN-029: API 容错"""

    def test_api_failure_logs_and_exits_zero(self, tmp_path):
        """正常模式 API 调用失败时，记录日志并 exit 0"""
        env = _make_env(tmp_path, with_sentinel=True)

        # 创建会失败的 stub gh
        stub_gh = tmp_path / "gh"
        stub_gh.write_text("#!/bin/bash\necho 'API error' >&2\nexit 1\n")
        stub_gh.chmod(0o755)

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, "正常模式 API 失败时应 exit 0（不 crash loop）"

        # 应记录错误日志
        log_file = Path(env["LOG_DIR"]) / "poll-releases.log"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "ERROR" in log_content or "失败" in log_content


class TestPollReleasesSentinel:
    """VAL-ANN-029: 哨兵机制"""

    def test_sentinel_missing_blocks_dispatch(self, tmp_path):
        """正常模式：无哨兵时禁绝派发（exit 0 但记错误日志）"""
        env = _make_env(tmp_path, with_sentinel=False)

        # 创建 stub gh（返回 release）
        releases = [
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.0.0",
            }
        ]
        _create_stub_gh(tmp_path, releases)

        # 创建 stub trigger（不应被调用）
        capture_file = tmp_path / "trigger_calls.log"
        _create_stub_trigger(tmp_path, capture_file)
        env["TRIGGER_SCRIPT"] = str(tmp_path / "trigger-release.sh")

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        # 应 exit 0（不 crash loop），但不应派发
        assert result.returncode == 0, "无哨兵时应 exit 0"

        # trigger 不应被调用
        if capture_file.exists():
            calls = capture_file.read_text().strip()
            assert calls == "", f"无哨兵时不应调用 trigger，实际调用：{calls}"

        # 应记录错误日志
        log_file = Path(env["LOG_DIR"]) / "poll-releases.log"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "哨兵" in log_content or "sentinel" in log_content.lower()

    def test_sentinel_present_allows_dispatch(self, tmp_path):
        """正常模式：有哨兵且 tag 无锁时，应正常派发"""
        env = _make_env(tmp_path, with_sentinel=True)

        # 创建 stub gh（返回 release）
        releases = [
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.0.0",
            }
        ]
        _create_stub_gh(tmp_path, releases)

        # 创建 stub trigger（应被调用）
        capture_file = tmp_path / "trigger_calls.log"
        _create_stub_trigger(tmp_path, capture_file)
        env["TRIGGER_SCRIPT"] = str(tmp_path / "trigger-release.sh")

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, "有哨兵时应成功退出"

        # trigger 应被调用
        assert capture_file.exists(), "有哨兵时 trigger 应被调用"
        calls = capture_file.read_text().strip()
        assert calls != "", "有哨兵且 tag 无锁时应派发"
        assert "v1.0.0" in calls


class TestPollReleasesListStyle:
    """VAL-ANN-029: 列表式轮询，latest 与非 latest 一视同仁"""

    def test_discovers_all_non_draft_releases(self, tmp_path):
        """遍历全部非 draft release，不区分 latest"""
        env = _make_env(tmp_path, with_sentinel=True)

        # 创建 stub gh（返回多个 release，含非 latest）
        releases = [
            {
                "tag_name": "v3.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v3.0.0",
            },
            {
                "tag_name": "v2.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v2.0.0",
            },
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.0.0",
            },
        ]
        _create_stub_gh(tmp_path, releases)

        # 创建 stub trigger
        capture_file = tmp_path / "trigger_calls.log"
        _create_stub_trigger(tmp_path, capture_file)

        env["TRIGGER_SCRIPT"] = str(tmp_path / "trigger-release.sh")

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0

        # 应调用 trigger 三次（每个 release 一次）
        assert capture_file.exists()
        calls = capture_file.read_text().strip().split("\n")
        assert len(calls) == 3, f"应调用 3 次 trigger，实际 {len(calls)} 次"

        # 验证三个 tag 都被发现
        tags = [line.split("|")[0] for line in calls]
        assert set(tags) == {"v3.0.0", "v2.0.0", "v1.0.0"}

    def test_skips_draft_releases(self, tmp_path):
        """跳过 draft release"""
        env = _make_env(tmp_path, with_sentinel=True)

        # 创建 stub gh（含 draft）
        releases = [
            {
                "tag_name": "v2.0.0",
                "draft": False,
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v2.0.0",
            },
            {
                "tag_name": "v1.5.0-rc1",
                "draft": True,  # draft
                "html_url": "https://github.com/hdot123-org/infra-core/releases/tag/v1.5.0-rc1",
            },
        ]
        _create_stub_gh(tmp_path, releases)

        # 创建 stub trigger
        capture_file = tmp_path / "trigger_calls.log"
        _create_stub_trigger(tmp_path, capture_file)

        env["TRIGGER_SCRIPT"] = str(tmp_path / "trigger-release.sh")

        result = subprocess.run(
            [str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0

        # 应只调用一次（跳过 draft）
        if capture_file.exists():
            calls = capture_file.read_text().strip().split("\n")
            assert len(calls) == 1, f"应只调用 1 次（跳过 draft），实际 {len(calls)} 次"
            tag = calls[0].split("|")[0]
            assert tag == "v2.0.0", "应只发现非 draft release"


class TestPollReleasesShellQuality:
    """工程门禁"""

    def test_shellcheck_zero_warnings(self):
        """shellcheck 零告警"""
        result = subprocess.run(
            ["shellcheck", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"shellcheck failed:\n{result.stdout}\n{result.stderr}"

    def test_bash_syntax_check(self):
        """bash -n 通过"""
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_bash_3_2_compatible(self, tmp_path):
        """bash 3.2 运行时兼容"""
        env = _make_env(tmp_path, with_sentinel=True)

        # 创建 stub gh
        releases = [{"tag_name": "v1.0.0", "draft": False, "html_url": "https://example.com"}]
        _create_stub_gh(tmp_path, releases)

        # 用系统 bash（3.2.57 on macOS）运行
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"bash 3.2 failed:\n{result.stderr}"

    def test_manifest_registration(self):
        """MANIFEST.sh 登记 poll-releases.sh"""
        manifest_path = REPO_ROOT / "webhook-scripts" / "MANIFEST.sh"
        content = manifest_path.read_text()
        assert "poll-releases.sh" in content, "MANIFEST.sh 应登记 poll-releases.sh"
