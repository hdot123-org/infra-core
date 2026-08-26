"""治理自检：受保护路径的修改权限检查

infra-core 自身的 governance 门禁（workflow 名 `Evolution Governance`）的核心逻辑。
fail-closed：无法判定时拒绝，绝不静默放行。

设计约束（VAL-SCAF-006）：
- 路径感知：只有当 PR 实际改动受保护路径时才要求 owner 身份
- 参数化：owner-login 与 protected-patterns 由调用方传入
- 可 dry-run：本地以 changed-files 列表 + author 参数即可验证判定表
"""

from __future__ import annotations

import fnmatch
import sys
from dataclasses import dataclass

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


@dataclass(frozen=True)
class GovernanceVerdict:
    """治理判定结果"""

    allowed: bool
    touched_protected: bool
    matched_patterns: tuple[str, ...]
    touched_files: tuple[str, ...]
    reason: str


def _match_any(path: str, patterns: tuple[str, ...]) -> list[str]:
    """返回与 path 匹配的模式列表

    目录模式（如 `.evolution/**`）同时覆盖目录本身与所有子孙路径。
    """
    matched: list[str] = []
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            matched.append(pattern)
            continue
        # `.evolution/**` 应匹配 `.evolution/config.yml`：
        # fnmatch 的 `**` 语义是"任意字符含 /"，但 `.evolution` 目录条目本身
        # （路径恰为 `.evolution`）也需要覆盖——用前缀判定补齐。
        prefix = pattern.split("/**", 1)[0]
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            matched.append(pattern)
    return matched


def check_governance(
    changed_files: list[str],
    pr_author: str,
    owner_login: str = DEFAULT_OWNER_LOGIN,
    protected_patterns: tuple[str, ...] | list[str] = DEFAULT_PROTECTED_PATTERNS,
) -> GovernanceVerdict:
    """判定一次 PR 变更是否放行

    判定表（fail-closed）：
    - author 未知（空）→ 拒绝（无法认证身份）
    - 未触碰受保护路径 → 放行（与作者无关）
    - 触碰受保护路径 + author == owner → 放行
    - 触碰受保护路径 + author != owner → 拒绝
    """
    patterns = tuple(protected_patterns)

    if not pr_author:
        return GovernanceVerdict(
            allowed=False,
            touched_protected=False,
            matched_patterns=(),
            touched_files=tuple(changed_files),
            reason="PR 作者身份未知（fail-closed 拒绝）",
        )

    matched: dict[str, list[str]] = {}
    touched: list[str] = []
    for path in changed_files:
        hits = _match_any(path, patterns)
        if hits:
            matched[path] = hits
            touched.append(path)

    if not touched:
        return GovernanceVerdict(
            allowed=True,
            touched_protected=False,
            matched_patterns=(),
            touched_files=tuple(changed_files),
            reason="未触碰受保护路径，放行",
        )

    if pr_author == owner_login:
        return GovernanceVerdict(
            allowed=True,
            touched_protected=True,
            matched_patterns=tuple(sorted({p for hits in matched.values() for p in hits})),
            touched_files=tuple(touched),
            reason=f"owner（{owner_login}）修改受保护路径，放行",
        )

    return GovernanceVerdict(
        allowed=False,
        touched_protected=True,
        matched_patterns=tuple(sorted({p for hits in matched.values() for p in hits})),
        touched_files=tuple(touched),
        reason=f"非 owner（{pr_author}）修改受保护路径，只有 {owner_login} 可以修改："
        + ", ".join(sorted({p for hits in matched.values() for p in hits})),
    )


def _parse_patterns(raw: str) -> tuple[str, ...]:
    """解析逗号分隔的模式串（composite action input 形态）"""
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：供 workflow 与本地 dry-run 复用

    用法：
        python -m infra_core.governance \
            --author <login> [--owner <login>] [--patterns <逗号分隔模式>] \
            [--files <路径>]... [--files-from <文件，每行一个路径>]

    退出码：0 放行 / 1 拒绝 / 2 用法或输入错误
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="infra-governance-check",
        description="治理自检：受保护路径修改权限判定（fail-closed）",
    )
    parser.add_argument("--author", required=True, help="PR 作者 login")
    parser.add_argument("--owner", default=DEFAULT_OWNER_LOGIN, help="owner login（默认 hdot123）")
    parser.add_argument(
        "--patterns",
        default=",".join(DEFAULT_PROTECTED_PATTERNS),
        help="受保护路径模式（逗号分隔，fnmatch 语法）",
    )
    parser.add_argument(
        "--files",
        action="append",
        default=[],
        help="变更文件路径（可重复传入）",
    )
    parser.add_argument(
        "--files-from",
        dest="files_from",
        help="从文件读取变更路径（每行一个，忽略空行；'-' 表示 stdin）",
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

    verdict = check_governance(
        changed_files=files,
        pr_author=args.author,
        owner_login=args.owner,
        protected_patterns=_parse_patterns(args.patterns),
    )

    if verdict.touched_protected:
        print(f"受保护路径变更：{', '.join(verdict.touched_files)}")
        print(f"命中模式：{', '.join(verdict.matched_patterns)}")
    print(("✓ " if verdict.allowed else "❌ ") + verdict.reason)
    return EXIT_ALLOW if verdict.allowed else EXIT_DENY


if __name__ == "__main__":
    sys.exit(main())
