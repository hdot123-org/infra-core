"""Shared dual-form inputs contract helpers (INFRA-670 dedup).

INFRA-670: ``TestDualFormInputs`` contract methods had 100% AST similarity
across test_droid_review_watchdog_handlers_workflow.py (L192/L212) and
test_droid_review_shards_workflow.py (L112/L140)
(CODE_HYGIENE_DUPLICATE_BLOCK). Both files assert the same
CONSUMER-GATE-DEADLOCK contract (2026-08-30): every snake input key must
carry a hyphen variant (required: false) and consumption sites must fuse
``inputs.x_snake || inputs['x-hyphen']`` — they differ only in the key set
and the workflow under test.

The shared assertion bodies are folded here. Test classes keep their local
``DUAL_FORM_SNAKE_KEYS`` and docstrings; methods delegate so existing test
IDs stay unchanged.

Pattern follows tests/drift_watch_helpers.py (INFRA-415).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def assert_hyphen_variants_declared_optional(
    workflow_call: dict[str, Any],
    snake_keys: tuple[str, ...],
    *,
    value_type: str | None = None,
) -> None:
    """Every snake key must carry an optional hyphen variant input.

    Args:
        workflow_call: parsed ``on.workflow_call`` mapping of the workflow.
        snake_keys: snake_form input names that must have hyphen variants.
        value_type: optional expected ``type`` of the variant
            (e.g. "string" for the shards workflow; None skips the check).
    """
    inputs = workflow_call.get("inputs", {})
    for snake in snake_keys:
        hyphen = snake.replace("_", "-")
        assert hyphen in inputs, f"缺少 hyphen 变体 input: {hyphen}"
        assert inputs[hyphen]["required"] is False, f"{hyphen} 变体必须可选"
        if value_type is not None:
            assert inputs[hyphen]["type"] == value_type, f"{hyphen} 变体 type 必须为 {value_type}"


def assert_no_bare_snake_input_consumption(
    workflow_path: Path, snake_keys: tuple[str, ...]
) -> None:
    """Declared hyphen variants must never be bypassed by bare snake reads.

    Guards against future consumption sites reading ``${{ inputs.x_snake }}``
    directly instead of the fused ``inputs.x_snake || inputs['x-hyphen']``
    expression (which would break single-form callers).
    """
    raw = workflow_path.read_text(encoding="utf-8")
    for snake in snake_keys:
        bare = "${{ inputs.%s }}" % snake
        hyphen = snake.replace("_", "-")
        assert bare not in raw, (
            f"inputs.{snake} 存在裸取消费点——必须熔合 inputs.{snake} || inputs['{hyphen}']"
        )
