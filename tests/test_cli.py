"""CLI 测试"""

from unittest.mock import patch

from infra_core.cli import cmd_audit, cmd_version_sweep, main


def test_infra_cli_help(capsys):
    """测试 infra-cli --help 安全无副作用"""
    with patch("sys.argv", ["infra-cli", "--help"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "infra-cli" in captured.out
    assert "scan" in captured.out
    assert "audit" in captured.out
    assert "version-sweep" in captured.out


def test_scan_help(capsys):
    """测试 scan --help"""
    with patch("sys.argv", ["infra-cli", "scan", "--help"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "--repo-root" in captured.out
    assert "--report-only" in captured.out


def test_audit_help(capsys):
    """测试 audit --help"""
    with patch("sys.argv", ["infra-cli", "audit", "--help"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "--target" in captured.out


def test_version_sweep_help(capsys):
    """测试 version-sweep --help"""
    with patch("sys.argv", ["infra-cli", "version-sweep", "--help"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert "--target" in captured.out


class _Args:
    """简单 mock args 对象"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_audit_skeleton_fails_gracefully(tmp_path, capsys):
    """测试 audit 骨架优雅失败"""
    result = cmd_audit(_Args(target=str(tmp_path)))
    assert result == 1
    captured = capsys.readouterr()
    assert "尚未实现" in captured.err


def test_version_sweep_skeleton_fails_gracefully(tmp_path, capsys):
    """测试 version-sweep 骨架优雅失败"""
    result = cmd_version_sweep(_Args(target=str(tmp_path)))
    assert result == 1
    captured = capsys.readouterr()
    assert "尚未实现" in captured.err


def test_audit_nonexistent_target(capsys):
    """测试 audit 不存在的路径"""
    result = cmd_audit(_Args(target="/nonexistent/path"))
    assert result == 1
    captured = capsys.readouterr()
    assert "不存在" in captured.err
