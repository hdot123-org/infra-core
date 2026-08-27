#!/usr/bin/env python3
"""BOUNDARY pollution guard for infra-core (public engine repo).

Adapted from memory-core scripts/check_boundary.py: preserves the
original architecture (BUSINESS_PREFIX/LEAK_PATTERN rule tables, git-tracked
file filtering, exemption path fragments, directory pruning) and
defensive patterns (TD-503-02 instant retry in sibling scripts),
but the rule tables target infra-core semantics:

- infra-core is a public engine repo, not a per-project knowledge store.
- Protects src/infra_core/**, .github/workflows/**, actions/**, docs/**.
- Rejects /Users/... local absolute paths, hardcoded secrets, org-internal
  details.

Usage:
    python scripts/check_boundary.py
    python scripts/check_boundary.py --json

Exit codes:
    0 — clean
    1 — violations detected
    2 — script error
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# --- Rule tables (preserved from memory-core, adapted for infra-core) ---

# 本地绝对路径泄漏模式（公开仓库严禁硬编码本地路径）。
# 对应 memory-core 原版的 LEAK_PATTERNS 中的 private-ip-192.168.88 等条目，
# 这里换为公开仓库的绝对路径禁令。
LEAK_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("local-abs-path-users", re.compile(r"/Users/\S+")),
    ("local-abs-path-home", re.compile(r"/home/\S+")),
    (
        "hardcoded-secret",
        re.compile(
            r"""(?i)(api[_\-]?key|token|password|secret)"""
            r"""\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}["']"""
        ),
    ),
)

# 业务专属文件名前缀（保留全量——infra-core 同样拒绝业务项目专属知识污染）。
BUSINESS_PREFIX_PATTERNS: tuple[str, ...] = (
    "workbot-",
    "axonhub-",
    "AEdu-",
    "youzy-",
)

# 公开仓库受保护路径域（不应出现业务项目状态文件）。
PROTECTED_DOMAINS: tuple[str, ...] = (
    "src/infra_core/",
    ".github/workflows/",
    "actions/",
    "docs/",
)

# 豁免路径段——出现在文件路径任意位置时跳过内容扫描。
EXEMPT_PATH_FRAGMENTS: tuple[str, ...] = (
    "/__pycache__/",
    ".pyc",
    "/.git/",
    "/.venv/",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "*.egg-info/",
    "build/",
    "dist/",
    "droid-wiki/",
    "memory/",  # memory-core 协议文件（memory-hook 自动产物）
    "project-map/",  # memory-core 协议文件
    "INDEX.md",
    "NOW.md",
    "tests/fixtures/",  # 测试 fixture 中可能包含示例路径
    "scripts/check_boundary.py",  # 自身（正则模式字符串）
    "tests/test_boundary_guard.py",  # 测试（引用规则模式）
    # behavior-equivalent transplant exception (AGENTS.md)
    "src/infra_core/engine/evolution_adapters.py",
)

# 目录名快速跳过（避免慢遍历）。
_EXEMPT_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "artifacts",
        "log",
        "build",
        "dist",
        "droid-wiki",
        "memory",
        "project-map",
    }
)


def _is_exempt(path: Path) -> bool:
    s = str(path)
    return any(frag in s for frag in EXEMPT_PATH_FRAGMENTS)


def _is_dir_exempt(dir_path: Path) -> bool:
    return dir_path.name in _EXEMPT_DIR_NAMES


def _get_git_tracked_files(repo_root: Path) -> set[Path] | None:
    """Return set of git-tracked file paths relative to *repo_root*.

    Returns None when git is unavailable — callers fall back to scanning all.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    return {repo_root / p for p in result.stdout.split("\0") if p}


def scan_protected_domain_leaks() -> list[dict[str, str]]:
    """Scan protected domains for local path leaks and hardcoded secrets."""
    findings: list[dict[str, str]] = []
    compiled = [(name, rx) for name, rx in LEAK_PATTERNS]
    tracked_files = _get_git_tracked_files(REPO_ROOT)

    for domain in PROTECTED_DOMAINS:
        domain_root = REPO_ROOT / domain
        if not domain_root.is_dir():
            continue

        for dirpath, dirnames, filenames in os.walk(domain_root, topdown=True):
            dirnames[:] = [d for d in dirnames if not _is_dir_exempt(Path(dirpath) / d)]

            for filename in filenames:
                filepath = Path(dirpath) / filename
                if _is_exempt(filepath):
                    continue

                # Only scan git-tracked files (untracked files won't be pushed)
                if tracked_files is not None and filepath not in tracked_files:
                    continue

                # Skip binary files
                try:
                    with open(filepath, "rb") as f:
                        chunk = f.read(8192)
                        if b"\x00" in chunk:
                            continue
                except (OSError, PermissionError):
                    continue

                try:
                    text = filepath.read_text(encoding="utf-8", errors="replace")
                except (OSError, PermissionError):
                    continue

                for name, regex in compiled:
                    m = regex.search(text)
                    if m:
                        line_no = text[: m.start()].count("\n") + 1
                        findings.append(
                            {
                                "kind": "protected-domain-leak",
                                "path": str(filepath.relative_to(REPO_ROOT)),
                                "line": str(line_no),
                                "matched": name,
                                "rule": (
                                    "BOUNDARY: protected domain must not contain "
                                    "local paths / hardcoded secrets / org-internal info"
                                ),
                            }
                        )

    return findings


def scan_business_file_names() -> list[dict[str, str]]:
    """Scan for business-project-prefixed file names in protected domains."""
    findings: list[dict[str, str]] = []
    for domain in PROTECTED_DOMAINS:
        domain_root = REPO_ROOT / domain
        if not domain_root.is_dir():
            continue
        for entry in domain_root.rglob("*"):
            if not entry.is_file():
                continue
            if _is_exempt(entry):
                continue
            for prefix in BUSINESS_PREFIX_PATTERNS:
                if entry.name.startswith(prefix):
                    findings.append(
                        {
                            "kind": "business-file-prefix",
                            "path": str(entry.relative_to(REPO_ROOT)),
                            "matched": prefix,
                            "rule": (
                                "BOUNDARY 4.1: business-prefixed files must not "
                                "appear in the public engine repo"
                            ),
                        }
                    )
                    break
    return findings


def main() -> int:
    # Restore script dir to sys.path (PYTHONSAFEPATH blocks auto-insert;
    # same P1-A pattern as evolution_scanner.py).
    _script_dir = str(Path(__file__).resolve().parent)
    if _script_dir not in sys.path:
        sys.path.insert(0, _script_dir)
    from guard_cli import run_cli

    def _format(f: dict[str, str]) -> str:
        loc = f"{f['path']}:{f.get('line', '-')}"
        return f"  [{f['kind']}] {loc}  matched={f['matched']!r}\n    rule: {f['rule']}"

    return run_cli(
        label="BOUNDARY guard",
        description="infra-core BOUNDARY pollution guard (public repo)",
        collect_findings=lambda: scan_protected_domain_leaks() + scan_business_file_names(),
        format_finding=_format,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"check_boundary.py: error: {exc}", file=sys.stderr)
        sys.exit(2)
