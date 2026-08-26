"""自进化引擎模块（M2 移植）"""

from .evolution_scanner import Finding, load_config, normalize_finding, run_audit_tool
from .version_sync import (
    _default_resign,
    get_resign_hook,
    probe_version_and_sync,
    set_resign_hook,
    sync_all_known_projects,
    sync_single_project,
)

__all__ = [
    "Finding",
    "load_config",
    "normalize_finding",
    "run_audit_tool",
    # version_sync (M3)
    "_default_resign",
    "get_resign_hook",
    "probe_version_and_sync",
    "set_resign_hook",
    "sync_all_known_projects",
    "sync_single_project",
]
