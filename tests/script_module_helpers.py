"""Helper utilities for loading script modules in tests."""

import importlib.util
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


def init_test_git_repo(repo_path: Path) -> None:
    """Initialize a minimal git repository for testing."""
    import subprocess

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
