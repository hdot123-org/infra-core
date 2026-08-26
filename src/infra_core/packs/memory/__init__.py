"""Memory rule pack for infra-core.

Provides audit tools migrated from memory-core:
- layout_audit: project memory layout audit (classifier injection)
- daily_audit: daily KB audit family
- hygiene: code hygiene audit (silent exception swallowing)
- error_patterns: error pattern detector
- self_audit: evolution self-audit (10 checks)
"""

from .pack import (
    ADAPTERS,
    TOOL_TO_CATEGORIES,
    get_categories,
    get_tool_names,
    get_tool_specs,
)

__all__ = [
    "ADAPTERS",
    "TOOL_TO_CATEGORIES",
    "get_categories",
    "get_tool_names",
    "get_tool_specs",
]
