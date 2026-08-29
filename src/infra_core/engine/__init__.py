"""自进化引擎模块（M2 移植）。

M4 起改为 PEP 562 lazy export：``import infra_core.engine.version_sync``
不再连带 import evolution_scanner。原因：engine 模块内部沿用移植保真的
裸名 import 链（``from evolution_utils import ...``），而消费仓（memory-core
scripts/）存在**同名裸名模块**；若消费仓测试进程先装载了自己的
``evolution_utils``，强制级的 scanner import 会解析到消费仓副本并因
API 漂移（如 INFRA-601 gh_repo_args）在 import 期即崩——memory-core 全量
pytest（xdist）实证。version_sync 集成面（消费仓 M3 缝合调用）不需要
scanner，lazy 化消除该碰撞面；包级旧导出名经 __getattr__ 保持兼容。
"""

from typing import Any

# 旧包级导出 → 所属子模块（保持 M2-M4 期间 from infra_core.engine import X 兼容）
_LAZY_ATTRS: dict[str, str] = {
    # evolution_scanner
    "Finding": "evolution_scanner",
    "load_config": "evolution_scanner",
    "normalize_finding": "evolution_scanner",
    "run_audit_tool": "evolution_scanner",
    # version_sync
    "_default_resign": "version_sync",
    "get_resign_hook": "version_sync",
    "probe_version_and_sync": "version_sync",
    "set_resign_hook": "version_sync",
    "sync_all_known_projects": "version_sync",
    "sync_single_project": "version_sync",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_ATTRS])
