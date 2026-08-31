"""Helper utilities for loading script modules in tests."""

import importlib.util
import subprocess
import sys
from pathlib import Path


def load_script_module(script_path: Path, module_name: str):
    """Dynamically load a script as a module for testing.

    This allows testing script functions without executing them as main programs.
    """
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


def run_cli_json_contract(script_path: Path, repo_root: Path) -> None:
    """共享的 guard 脚本 ``--json`` CLI 契约断言（INFRA-696）。

    多个 guard 契约测试（check_boundary / check_doc_classification）此前各自
    内联同一段 ``--json`` 冒烟断言，触发 CODE_HYGIENE_DUPLICATE_BLOCK
    （同名函数 test_cli_json_output 100% AST 相似）。收敛到本 helper 单点维护，
    各测试文件只保留薄包装调用。
    """
    result = subprocess.run(
        [sys.executable, str(script_path), "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "findings" in result.stdout, "JSON output must contain 'findings'"
    assert "count" in result.stdout, "JSON output must contain 'count'"


def run_live_repo_clean_contract(script_path: Path, repo_root: Path, check_name: str) -> None:
    """共享的 guard 脚本 live-repo-clean 契约断言（INFRA-697）。

    check_boundary 与 check_doc_classification 的 test_live_repo_clean 此前
    各自内联同一段「对真实仓库跑一遍、期望 exit 0」断言（97% AST 相似），
    触发 CODE_HYGIENE_DUPLICATE_BLOCK。收敛到本 helper 单点维护，差异化的
    失败提示文案由 *check_name* 参数提供。
    """
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Live repo failed {check_name} check:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def init_test_git_repo(repo_path: Path) -> None:
    """Initialize a minimal git repository for testing."""
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
