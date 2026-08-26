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
    ) -> None:
        self.name = name
        self.command_template = command_template
        self.category = category
        self.description = description
        self.timeout = timeout
        self.classifier_injected = classifier_injected

    def to_config_dict(self) -> dict[str, Any]:
        """Convert to audit_tools config entry."""
        return {
            "name": self.name,
            "command": self.command_template,
            "output_format": "json",
            "timeout": self.timeout,
        }


# Tool specifications for the memory pack
TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="daily_kb_audit",
        command_template="infra-daily-audit --repo-root {repo_root} --json",
        category="daily_audit",
        description="Daily KB audit: checks memory system integrity and freshness",
        timeout=120,
    ),
    ToolSpec(
        name="layout_audit",
        command_template="infra-layout-audit --target {repo_root} --json",
        category="layout",
        description="Project memory layout audit: validates structure and conventions",
        timeout=60,
        classifier_injected=True,
    ),
    ToolSpec(
        name="code_hygiene",
        command_template="infra-hygiene-audit --repo-root {repo_root} --json",
        category="hygiene",
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
TOOL_TO_CATEGORIES: dict[str, set[str]] = {
    "daily_kb_audit": {"daily_audit"},
    "layout_audit": {"layout"},
    "code_hygiene": {"hygiene"},
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
