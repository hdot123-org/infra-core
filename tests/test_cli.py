"""CLI 测试"""

import subprocess
import sys
from pathlib import Path


def test_infra_cli_help():
    """测试 infra-cli --help 安全无副作用"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "infra-cli" in result.stdout
    assert "scan" in result.stdout
    assert "audit" in result.stdout
    assert "version-sweep" in result.stdout


def test_scan_help():
    """测试 scan --help"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "scan", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--repo-root" in result.stdout
    assert "--report-only" in result.stdout


def test_audit_help():
    """测试 audit --help"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "audit", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--target" in result.stdout


def test_version_sweep_help():
    """测试 version-sweep --help"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "version-sweep", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--target" in result.stdout


def test_audit_skeleton_fails_gracefully(tmp_path):
    """测试 audit 骨架优雅失败"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "audit", "--target", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "尚未实现" in result.stderr
    assert "Traceback" not in result.stderr


def test_version_sweep_skeleton_fails_gracefully(tmp_path):
    """测试 version-sweep 骨架优雅失败"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "version-sweep", "--target", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "尚未实现" in result.stderr
    assert "Traceback" not in result.stderr


def test_audit_nonexistent_target():
    """测试 audit 不存在的路径"""
    result = subprocess.run(
        [sys.executable, "-m", "infra_core.cli", "audit", "--target", "/nonexistent/path"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "不存在" in result.stderr
    assert "Traceback" not in result.stderr
