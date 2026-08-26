#!/usr/bin/env python3
"""治理自检 action 内嵌脚本（自包含，无第三方依赖）

与 src/infra_core/governance.py 保持判定等价（fail-closed + 路径感知 fnmatch）。
本文件自包含是因为 composite action 可能被消费仓在任意 base 上使用，
不能假设 infra-core 包已安装。判定逻辑的契约测试在 tests/test_governance.py
与 tests/test_naming_contract.py（对两者的判定等价性也有断言）。

用法（由 action.yml 调用）：
    governance_check.py --author <login> [--owner <login>] \
        [--patterns <逗号分隔>] [--files <路径>]... [--files-from <文件|->]

退出码：0 放行 / 1 拒绝 / 2 输入错误
"""

from __future__ import annotations

import argparse
import fnmatch
import sys

DEFAULT_OWNER_LOGIN = "hdot123"
DEFAULT_PROTECTED_PATTERNS = (
    ".evolution/**",
    ".github/workflows/**",
    "src/infra_core/engine/**",
    "webhook-scripts/**",
)

EXIT_ALLOW = 0
EXIT_DENY = 1
EXIT_ERROR = 2


def _match_any(path: str, patterns: tuple[str, ...]) -> list[str]:
    """返回与 path 匹配的模式列表（目录模式覆盖目录条目本身）"""
    matched: list[str] = []
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            matched.append(pattern)
            continue
        prefix = pattern.split("/**", 1)[0]
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            matched.append(pattern)
    return matched


def check_governance(
    changed_files: list[str],
    pr_author: str,
    owner_login: str = DEFAULT_OWNER_LOGIN,
    protected_patterns: tuple[str, ...] | list[str] = DEFAULT_PROTECTED_PATTERNS,
) -> tuple[bool, str]:
    """返回 (allowed, reason)。判定表与 infra_core.governance 一致。"""
    patterns = tuple(protected_patterns)

    if not pr_author:
        return False, "PR 作者身份未知（fail-closed 拒绝）"

    matched_patterns: set[str] = set()
    touched: list[str] = []
    for path in changed_files:
        hits = _match_any(path, patterns)
        if hits:
            matched_patterns.update(hits)
            touched.append(path)

    if not touched:
        return True, "未触碰受保护路径，放行"

    if pr_author == owner_login:
        return True, f"owner（{owner_login}）修改受保护路径，放行"

    return (
        False,
        f"非 owner（{pr_author}）修改受保护路径，只有 {owner_login} 可以修改："
        + ", ".join(sorted(matched_patterns)),
    )


def _parse_patterns(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="governance-check",
        description="治理自检：受保护路径修改权限判定（fail-closed）",
    )
    parser.add_argument("--author", required=True, help="PR 作者 login")
    parser.add_argument("--owner", default=DEFAULT_OWNER_LOGIN, help="owner login")
    parser.add_argument(
        "--patterns",
        default=",".join(DEFAULT_PROTECTED_PATTERNS),
        help="受保护路径模式（逗号分隔，fnmatch 语法）",
    )
    parser.add_argument("--files", action="append", default=[], help="变更文件路径（可重复）")
    parser.add_argument(
        "--files-from",
        dest="files_from",
        help="从文件读取变更路径（每行一个；'-' 表示 stdin）",
    )
    args = parser.parse_args(argv)

    files: list[str] = list(args.files)
    if args.files_from:
        try:
            if args.files_from == "-":
                files.extend(line.strip() for line in sys.stdin if line.strip())
            else:
                with open(args.files_from, encoding="utf-8") as fh:
                    files.extend(line.strip() for line in fh if line.strip())
        except OSError as exc:
            print(f"错误：无法读取变更文件列表：{exc}", file=sys.stderr)
            return EXIT_ERROR

    if touched := [p for p in files if _match_any(p, _parse_patterns(args.patterns))]:
        print(f"受保护路径变更：{', '.join(touched)}")

    allowed, reason = check_governance(
        changed_files=files,
        pr_author=args.author,
        owner_login=args.owner,
        protected_patterns=_parse_patterns(args.patterns),
    )
    print(("✓ " if allowed else "❌ ") + reason)
    return EXIT_ALLOW if allowed else EXIT_DENY


if __name__ == "__main__":
    sys.exit(main())
