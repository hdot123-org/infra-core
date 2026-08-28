"""setup-venv composite action 契约测试（预装环境锁定第 3 层：fast-fail 加固）

checkout 残缺（runner 工作区中毒，2026-08-27 runner-02/03 事件）时，
composite 第一步必须立即以可操作错误失败，不让下游报迷惑性错误。
"""

from pathlib import Path

import yaml

ACTION_YAML = (
    Path(__file__).resolve().parents[1] / ".github" / "actions" / "setup-venv" / "action.yml"
)


def _load_action():
    return yaml.safe_load(ACTION_YAML.read_text(encoding="utf-8"))


def test_fast_fail_is_first_step():
    """fast-fail 步骤必须是 composite 的第一步"""
    steps = _load_action()["runs"]["steps"]
    assert steps[0]["name"] == "Fast-fail on incomplete checkout"
    assert steps[0]["shell"] == "bash"


def test_fast_fail_checks_key_files():
    """检查三件关键文件：.git / pyproject.toml / setup-venv action.yml 自身"""
    run = _load_action()["runs"]["steps"][0]["run"]
    for key in (".git", "pyproject.toml", ".github/actions/setup-venv/action.yml"):
        assert key in run, f"fast-fail 未检查关键文件：{key}"


def test_fast_fail_carries_actionable_message():
    """错误消息含 'checkout 残缺' 指引（rerun / 清工作区）并以非零退出"""
    run = _load_action()["runs"]["steps"][0]["run"]
    assert "checkout 残缺" in run
    assert "rerun" in run or "重跑" in run
    assert "exit 1" in run


def test_fast_fail_uses_github_error_annotation():
    """使用 ::error:: 注解让失败在 GitHub UI 醒目可见"""
    run = _load_action()["runs"]["steps"][0]["run"]
    assert "::error::" in run
