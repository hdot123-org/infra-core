"""infra-cli: 统一命令行入口"""

import argparse
import sys
from pathlib import Path


def cmd_scan(args: argparse.Namespace) -> int:
    """scan 子命令（M2 移植后实现）"""
    print("scan 子命令尚未实现（M2 移植后提供）", file=sys.stderr)
    print("提示：M2 完成后将支持 --repo-root 和 --report-only 参数", file=sys.stderr)
    return 1


def cmd_audit(args: argparse.Namespace) -> int:
    """audit 子命令（M3 规则包迁入后实现）"""
    target = Path(args.target) if args.target else Path.cwd()

    if not target.exists():
        print(f"错误：目标路径不存在：{target}", file=sys.stderr)
        return 1

    if not target.is_dir():
        print(f"错误：目标不是目录：{target}", file=sys.stderr)
        return 1

    # M3 前骨架状态：优雅失败
    print("audit 子命令尚未实现（M3 规则包迁入后提供）", file=sys.stderr)
    print(f"目标路径：{target}", file=sys.stderr)
    return 1


def cmd_version_sweep(args: argparse.Namespace) -> int:
    """version-sweep 子命令（M3 version_sync 迁移后实现）"""
    target = Path(args.target) if args.target else Path.cwd()

    if not target.exists():
        print(f"错误：目标路径不存在：{target}", file=sys.stderr)
        return 1

    if not target.is_dir():
        print(f"错误：目标不是目录：{target}", file=sys.stderr)
        return 1

    # M3 前骨架状态：优雅失败
    print("version-sweep 子命令尚未实现（M3 version_sync 迁移后提供）", file=sys.stderr)
    print(f"目标路径：{target}", file=sys.stderr)
    return 1


def main() -> int:
    """infra-cli 主入口"""
    parser = argparse.ArgumentParser(
        prog="infra-cli",
        description="组织级演进引擎 CLI",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用子命令")

    # scan 子命令
    scan_parser = subparsers.add_parser("scan", help="扫描仓库（M2 实现）")
    scan_parser.add_argument("--repo-root", type=str, help="目标仓库路径（默认当前目录）")
    scan_parser.add_argument("--report-only", action="store_true", help="只读模式，不创建 issue")
    scan_parser.add_argument("--output", type=str, help="输出报告路径")

    # audit 子命令
    audit_parser = subparsers.add_parser("audit", help="审计项目（M3 实现）")
    audit_parser.add_argument("--target", type=str, help="目标项目路径（默认当前目录）")

    # version-sweep 子命令
    sweep_parser = subparsers.add_parser("version-sweep", help="版本同步（M3 实现）")
    sweep_parser.add_argument("--target", type=str, help="目标项目路径（默认当前目录）")
    sweep_parser.add_argument("--all", action="store_true", help="全局模式：同步所有已知项目")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "version-sweep":
        return cmd_version_sweep(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
