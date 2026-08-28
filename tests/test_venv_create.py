"""infra-cli venv create 子命令测试（预装环境锁定第 3 层便利项）

定位说明（编排器评估结论）：venv create 是 setup-venv composite 的统一 CLI
入口，便利性优先；它不免疫仓库内容型 job 的 checkout 残缺（该防线在
composite 的 fast-fail 步骤）。
"""

import sys
from unittest.mock import patch

import pytest

from infra_core import cli

pytestmark = pytest.mark.integration


def _run_main(argv):
    """以给定 argv 运行 CLI main()，返回 (exit_code, stdout, stderr)。"""
    with patch("sys.argv", argv):
        try:
            code = cli.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    # main() 返回 int；SystemExit 已在上面归一
    return code, "", ""


def test_venv_help_lists_create(capsys):
    """venv --help 列出 create 子命令且安全退出"""
    with patch("sys.argv", ["infra-cli", "venv", "--help"]):
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
    out = capsys.readouterr().out
    assert "create" in out


def test_venv_create_help_documents_flags(capsys):
    """venv create --help 文档化 --path/--extras/--no-install"""
    with patch("sys.argv", ["infra-cli", "venv", "create", "--help"]):
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
    out = capsys.readouterr().out
    for flag in ("--path", "--extras", "--no-install"):
        assert flag in out


def test_venv_create_builds_real_venv(tmp_path, monkeypatch):
    """--no-install 模式真实创建 venv 并返回 0"""
    monkeypatch.chdir(tmp_path)
    code = _run_main(["infra-cli", "venv", "create", "--path", "test-venv", "--no-install"])[0]
    assert code == 0
    assert (tmp_path / "test-venv" / "bin" / "python").exists()


def test_venv_create_refuses_existing_nonempty_path(tmp_path, monkeypatch, capsys):
    """目标已存在且非空时优雅失败（非零退出、无 traceback）"""
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "somefile").write_text("x")
    monkeypatch.chdir(tmp_path)
    code = _run_main(["infra-cli", "venv", "create", "--path", "occupied"])[0]
    err = capsys.readouterr().err
    assert code != 0
    assert "Traceback" not in err
    assert "已存在" in err


def test_venv_create_install_missing_pyproject_fails_actionably(tmp_path, monkeypatch, capsys):
    """无 pyproject.toml 时请求安装：fast-fail 并给出可操作错误"""
    monkeypatch.chdir(tmp_path)  # 空目录：无 pyproject.toml
    code = _run_main(["infra-cli", "venv", "create", "--path", "v"])[0]
    err = capsys.readouterr().err
    assert code == 1
    assert "Traceback" not in err
    assert "pyproject.toml" in err
    # 可操作指引：重跑/清理 或 显式 --no-install
    assert "--no-install" in err


def test_venv_create_install_invokes_venv_pip_with_extras(tmp_path, monkeypatch):
    """有 pyproject.toml 时以 venv 解释器执行 pip install -e .[<extras>]"""
    from pathlib import Path as _Path

    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "v").mkdir()  # 目标存在但为空：通过 guard
    recorded = {}

    class _FakeProc:
        returncode = 0

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return _FakeProc()

    orig_exists = _Path.exists

    def fake_exists(self):
        # 仅对 venv 解释器路径返回 True，其余走真实检查
        if self.name == "python" and self.parent.name == "bin":
            return True
        return orig_exists(self)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(_Path, "exists", fake_exists)
    code = cli.cmd_venv_create(
        _ns(path=str(tmp_path / "v"), extras="dev", python=sys.executable, no_install=False)
    )
    assert code == 0
    venv_python = tmp_path / "v" / "bin" / "python"
    assert recorded["cmd"] == [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"]


class _ns:
    def __init__(self, **kw):
        self.path = kw["path"]
        self.extras = kw["extras"]
        self.python = kw["python"]
        self.no_install = kw["no_install"]
