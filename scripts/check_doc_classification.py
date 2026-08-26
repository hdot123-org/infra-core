#!/usr/bin/env python3
"""文档分类校验脚本。

扫描 docs/ 下所有文件，校验每个文件的父目录在注册分类中。
不在则 exit 1。

参考 memory-core scripts/check_doc_classification.py 模式。

用法：
    python scripts/check_doc_classification.py
    python scripts/check_doc_classification.py --json

退出码：
    0 — clean（所有文件在注册目录中）
    1 — 检测到未注册目录中的文件
    2 — 脚本自身出错
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# infra-core 文档分类路由表
# docs/ 下的子目录必须属于以下分类之一
DOC_CATEGORIES = {
    "architecture": "docs/architecture/",
    "guides": "docs/guides/",
    "specs": "docs/specs/",
    "infrastructure": "docs/infrastructure/",
}

# 例外目录（允许存在但不属于上述分类）
EXCEPTION_DIRS = ("docs/__pycache__/",)

# 顶层例外文件
TOP_LEVEL_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "docs/README.md",
        "docs/INDEX.md",
        "docs/architecture.md",  # 顶层架构概览文档
    }
)

# 扫描根目录
SCAN_ROOTS: tuple[Path, ...] = (REPO_ROOT / "docs",)

# 跳过的文件名模式
SKIP_FILES: frozenset[str] = frozenset(
    {
        ".DS_Store",
    }
)


def _is_exempt(path: Path) -> bool:
    """检查路径是否在豁免列表或跳过的文件中。"""
    path_str = str(path)
    # 跳过特定文件名
    if path.name in SKIP_FILES:
        return True
    # 跳过例外目录
    if any(exc_dir in path_str for exc_dir in EXCEPTION_DIRS):
        return True
    return False


def _is_in_registered_dir(file_path: Path, repo_root: Path | None = None) -> bool:
    """检查文件是否在注册的文档分类目录或例外目录中。"""
    root = repo_root or REPO_ROOT
    rel = str(file_path.relative_to(root))
    rel_dir = str(file_path.parent.relative_to(root)) + "/"

    # 顶层例外文件
    if rel in TOP_LEVEL_EXCEPTIONS:
        return True

    # 检查是否在注册的分类目录中
    for cat_dir in DOC_CATEGORIES.values():
        if rel_dir.startswith(cat_dir):
            return True

    # 检查是否在例外目录中
    return any(rel_dir.startswith(exc_dir) for exc_dir in EXCEPTION_DIRS)


def scan_doc_classification(
    scan_root: Path | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, str]]:
    """扫描 docs/ 目录，找出不在注册分类中的文件。"""
    findings: list[dict[str, str]] = []
    root = scan_root or REPO_ROOT / "docs"
    r_root = repo_root or REPO_ROOT

    if not root.is_dir():
        return findings

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_exempt(path):
            continue
        if _is_in_registered_dir(path, repo_root=r_root):
            continue
        findings.append(
            {
                "kind": "unregistered-doc-dir",
                "path": str(path.relative_to(r_root)),
                "rule": (
                    "File is not in any DOC_CATEGORIES directory or EXCEPTION_DIRS. "
                    "See scripts/check_doc_classification.py for the routing table."
                ),
            }
        )

    return findings


def main() -> int:
    # CLI skeleton shared with other guard scripts (INFRA-559).
    # Restore script dir to sys.path (PYTHONSAFEPATH blocks auto-insert).
    _script_dir = str(Path(__file__).resolve().parent)
    if _script_dir not in sys.path:
        sys.path.insert(0, _script_dir)
    from guard_cli import run_cli

    def _format(f: dict[str, str]) -> str:
        return f"  [{f['kind']}] {f['path']}\n    rule: {f['rule']}"

    return run_cli(
        label="doc classification guard",
        description="Document classification directory guard",
        collect_findings=scan_doc_classification,
        format_finding=_format,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"check_doc_classification.py: error: {exc}", file=sys.stderr)
        sys.exit(2)
