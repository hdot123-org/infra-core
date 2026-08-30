"""Memory rule pack registration.

This module defines the ToolSpec list, adapter registration, and tool-to-category
mapping for the memory rule pack. It is loaded by the scanner via the
infra_core.packs entry point.
"""

from __future__ import annotations

from typing import Any, Callable

# Type alias for classifier injection
ClassifierFn = Callable[[str], Any]


def default_classifier(rel_path: str) -> Any:
    """Default classifier using ownership_reader.

    This is the fallback when no classifier is injected. It loads
    ownership.toml from the project root and classifies the path.
    """
    from pathlib import Path

    from . import ownership_reader

    project_root = Path.cwd()
    return ownership_reader.classify_owned_path(rel_path, project_root=project_root)


class ToolSpec:
    """Specification for a pack tool."""

    def __init__(
        self,
        name: str,
        command_template: str,
        category: str,
        description: str,
        timeout: int = 60,
        classifier_injected: bool = False,
        output_format: str = "json",
    ) -> None:
        self.name = name
        self.command_template = command_template
        self.category = category
        self.description = description
        self.timeout = timeout
        self.classifier_injected = classifier_injected
        # "json" = stdout 为单个 JSON 对象；"jsonl" = stdout 每行一个 JSON
        # 对象（error_patterns --json 的原版行为）。scanner run_audit_tool
        # 按此声明选择解析路径，声明与实际输出不一致会静默丢结果。
        self.output_format = output_format

    def to_config_dict(self) -> dict[str, Any]:
        """Convert to audit_tools config entry."""
        return {
            "name": self.name,
            "command": self.command_template,
            "output_format": self.output_format,
            "timeout": self.timeout,
        }


# Tool specifications for the memory pack
#
# 命名契约锚点：工具名必须与 engine evolution_adapters 的 ADAPTER_MAP /
# TOOL_TO_CATEGORIES 键完全一致（audit_layout / code_hygiene_audit 是 engine
# 侧键名）。名字漂移会让 adapter 静默 no-op（raw 透传/类别追踪丢失）。
# 锁定测试：tests/test_pack_seam_contracts.py::TestToolNameContract。
TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="daily_kb_audit",
        # --no-infra：消费者扫描禁探测宿主 infrastructure inventory（SSH/TCP/
        # HTTP 越界探测）；--report-only：禁写宿主 ~/.memory-core/audit/
        # （M2 user-testing (b) 条款：消费者扫描零宿主写）。
        command_template=(
            "infra-daily-audit --repo-root {repo_root} --no-infra --report-only --json"
        ),
        category="daily_audit",
        description="Daily KB audit: checks memory system integrity and freshness",
        timeout=120,
    ),
    ToolSpec(
        name="audit_layout",
        command_template="infra-layout-audit --target {repo_root} --json",
        category="audit_layout",
        description="Project memory layout audit: validates structure and conventions",
        timeout=60,
        classifier_injected=True,
    ),
    ToolSpec(
        name="code_hygiene_audit",
        command_template="infra-hygiene-audit --repo-root {repo_root} --json",
        category="code_hygiene",
        description=(
            "Code hygiene audit: silent exception swallowing, untracked TODO/FIXME/HACK, "
            "duplicate code blocks"
        ),
        # 300s timeout: full-repo AST scan (parse + swallow visitor + tokenize
        # comment scan + pairwise AST-dump duplicate detection). Migrated from
        # memory-core code_hygiene_audit.py which uses the same 300s budget.
        timeout=300,
    ),
    ToolSpec(
        name="error_patterns",
        command_template="infra-error-patterns --repo-root {repo_root} --json",
        category="error_pattern",
        description="Error pattern detector: identifies recurring error signatures",
        timeout=120,
        # --json 输出为 JSONL（每行一条 registry entry，0/1/N 行皆可能）；
        # 声明 jsonl 走 run_audit_tool 的逐行解析路径。
        output_format="jsonl",
    ),
    ToolSpec(
        name="evolution_self_audit",
        command_template="infra-self-audit --repo-root {repo_root} --json",
        category="evolution_self_audit",
        description="Evolution self-audit: validates the evolution system itself",
        timeout=60,
    ),
]


# Adapter registry: maps tool name to adapter function
# Adapters normalize raw tool output to the standard Finding schema
ADAPTERS: dict[str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = {}


def register_adapter(
    tool_name: str,
    adapter_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> None:
    """Register an adapter function for a tool."""
    ADAPTERS[tool_name] = adapter_fn


# Tool-to-category mapping for history tracking
# 键与值都与 engine evolution_adapters.TOOL_TO_CATEGORIES 同键同值（契约锁定）。
TOOL_TO_CATEGORIES: dict[str, set[str]] = {
    "daily_kb_audit": {"daily_audit"},
    "audit_layout": {"audit_layout"},
    "code_hygiene_audit": {"code_hygiene"},
    "error_patterns": {"error_pattern"},
    "evolution_self_audit": {"evolution_self_audit"},
}


def get_tool_specs() -> list[dict[str, Any]]:
    """Get all tool specs as config dicts.

    Returns a list of audit_tools entries that can be merged into
    the scanner's tool inventory.
    """
    return [spec.to_config_dict() for spec in TOOL_SPECS]


def get_tool_names() -> list[str]:
    """Get the names of all tools in this pack."""
    return [spec.name for spec in TOOL_SPECS]


def get_categories() -> dict[str, set[str]]:
    """Get the tool-to-category mapping."""
    return TOOL_TO_CATEGORIES.copy()
