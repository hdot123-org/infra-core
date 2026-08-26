"""infra-cli: 统一命令行入口"""

import argparse
import json
import os
import sys
from pathlib import Path


def cmd_scan(args: argparse.Namespace) -> int:
    """scan 子命令：委托 engine.evolution_scanner 执行演进扫描

    引擎的 main() 通过 argparse 解析 sys.argv，因此这里把 CLI 解析好的
    参数重新组装为引擎 argv 并转发，保持单一实现（CLI 不做独立扫描逻辑）。
    """
    # 延迟导入：保证 `infra-cli --help` / `infra-cli scan --help` 不触发引擎
    # 加载副作用（VAL-ENG-004），也让未安装 pyyaml 的环境可用其余子命令
    from infra_core.engine import evolution_scanner

    repo_root = Path(args.repo_root).resolve()

    if not repo_root.exists():
        print(f"错误：目标路径不存在：{repo_root}", file=sys.stderr)
        return 1
    if not repo_root.is_dir():
        print(f"错误：目标不是目录：{repo_root}", file=sys.stderr)
        return 1

    engine_argv = ["infra-cli scan", "--repo-root", str(repo_root)]
    if args.report_only:
        engine_argv.append("--report-only")
    if args.output:
        engine_argv.extend(["--output", str(args.output)])

    original_argv = sys.argv
    try:
        sys.argv = engine_argv
        evolution_scanner.main()
    except SystemExit as e:
        # 引擎用 sys.exit 表达 tick 结果（P1-2/P2-A 硬退出码 1、kill switch 0）
        if e.code is None:
            return 0
        return e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = original_argv
    return 0


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
    """version-sweep 子命令：委托 engine.version_sync 执行版本同步"""
    from infra_core.engine import version_sync

    if args.all:
        # 全局模式：同步所有已知项目
        lifecycle_root = Path(args.lifecycle_root) if args.lifecycle_root else None
        result = version_sync.sync_all_known_projects(
            lifecycle_root=lifecycle_root,
            target_version=args.target_version,
            canonical_schema=args.canonical_schema,
        )
    else:
        # 单项目模式
        target = Path(args.target).resolve() if args.target else Path.cwd().resolve()

        if not target.exists():
            print(f"错误：目标路径不存在：{target}", file=sys.stderr)
            return 1

        if not target.is_dir():
            print(f"错误：目标不是目录：{target}", file=sys.stderr)
            return 1

        result = version_sync.sync_single_project(
            target, args.target_version, args.canonical_schema
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if "patched" in result and isinstance(result.get("patched"), list):
            for entry in result.get("patched", []):
                print(f"  [PATCH] {entry['name']}: {entry['from']} -> {entry['to']}")
            for entry in result.get("skipped", []):
                print(f"  [SKIP]  {entry['name']}: {entry['reason']}")
            for entry in result.get("errors", []):
                print(f"  [ERROR] {entry['name']}: {entry['reason']}")
        else:
            if result.get("patched"):
                print(f"Patched: {result['from']} -> {result['to']}")
            else:
                print(f"Skipped: {result.get('reason', 'unknown')}")

    return 0


def main() -> int:
    """infra-cli 主入口"""
    parser = argparse.ArgumentParser(
        prog="infra-cli",
        description="组织级演进引擎 CLI",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用子命令")

    # scan 子命令
    scan_parser = subparsers.add_parser("scan", help="扫描仓库（M2 实现）")
    scan_parser.add_argument(
        "--repo-root",
        type=str,
        default=os.getcwd(),
        help="目标仓库路径（默认当前目录）",
    )
    scan_parser.add_argument("--report-only", action="store_true", help="只读模式，不创建 issue")
    scan_parser.add_argument("--output", type=str, default=None, help="输出报告路径")

    # audit 子命令
    audit_parser = subparsers.add_parser("audit", help="审计项目（M3 实现）")
    audit_parser.add_argument("--target", type=str, help="目标项目路径（默认当前目录）")

    # version-sweep 子命令
    sweep_parser = subparsers.add_parser("version-sweep", help="版本同步（M3 实现）")
    sweep_parser.add_argument("--target", type=str, help="目标项目路径（默认当前目录）")
    sweep_parser.add_argument("--all", action="store_true", help="全局模式：同步所有已知项目")
    sweep_parser.add_argument(
        "--target-version", type=str, required=True, help="目标版本号（必填）"
    )
    sweep_parser.add_argument(
        "--canonical-schema",
        type=str,
        default="context-package-v1",
        help="规范 schema 版本（默认 context-package-v1）",
    )
    sweep_parser.add_argument("--lifecycle-root", type=str, help="lifecycle 根目录（全局模式使用）")
    sweep_parser.add_argument("--json", action="store_true", help="JSON 输出")

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
