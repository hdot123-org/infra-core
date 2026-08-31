"""Suppress drift guard for bundled-copy duplicate-block suppressions (INFRA-691).

抑制条目的 location 含行号与 md5 截断哈希——INFRA-670 判定其结构性弱点是
「engine 侧行漂移即失效」。本守卫从**实时源码**推导期望的抑制 key（与生产
管线同路径：hygiene 的 FuncInfo 行号 + evolution_adapters 的
sanitize_structured_field 归一化），与 .evolution/suppress.json 实际登记对账：

- 函数行号漂移 / 改名 / 删除 → 推导 key 与登记 key 失配 → 测试失败，
  强制同步更新 suppress.json（而非静默失效、下个 tick 重新滴灌 issue）
- 引擎与 action 副本字节契约破坏（TestBundledPublishCopy 失败）不在本守卫
  范围，由各自契约测试锁定

双副本背景：composite action 在 caller 仓库运行无法 import src/，副本必须
物理存在（自包含分发）；bytes-equal 契约见 TestBundledPublishCopy（publish_findings）
与 TestActionScriptEquivalence（governance_check，判定等价而非字节一致，
两文件行号不同：action L35 / engine L42）。
"""

import ast
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parent.parent
_engine_dir = REPO_ROOT / "src" / "infra_core" / "engine"
sys.path.insert(0, str(_engine_dir))

from evolution_adapters import sanitize_structured_field  # noqa: E402
from evolution_scanner import load_suppressions  # noqa: E402

RULE_ID = "CODE_HYGIENE_DUPLICATE_BLOCK"

# publish_findings 文件对的 8 个同名函数（bytes-equal 契约内必然同名同行号）
PUBLISH_FUNCTIONS = (
    "validate_findings",
    "deduplicate_findings",
    "group_by_shard",
    "count_by_severity",
    "load_findings_files",
    "post_inline_comment",
    "post_summary_comment",
    "main",
)

# governance 文件对只有一个超阈值的同名函数 _match_any（98% 相似）
GOVERNANCE_FUNCTIONS = ("_match_any",)

# (engine 相对路径, action 相对路径, 函数名元组)
BUNDLED_PAIRS = (
    (
        "src/infra_core/engine/droid_review/publish_findings.py",
        "actions/droid-review-aggregate/publish_findings.py",
        PUBLISH_FUNCTIONS,
    ),
    (
        "src/infra_core/governance.py",
        "actions/governance-check/governance_check.py",
        GOVERNANCE_FUNCTIONS,
    ),
)


def _function_def_lines(source: str, names: tuple[str, ...]) -> dict[str, int]:
    """Parse source and return {function_name: def line} for top-level functions."""
    tree = ast.parse(source)
    lines = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            lines[node.name] = node.lineno
    return lines


def _expected_suppression_keys() -> set[tuple[str, str]]:
    """Derive expected suppression keys from live source (production pipeline shape).

    与 scanner 管线同构：hygiene 的 location 原文是
    ``{a.file}::L{a.line_no} <-> {b.file}::L{b.line_no}``（os.walk 顺序不定，
    两种顺序都要登记），随后 normalize_finding 套 sanitize_structured_field
    （>100 字符截断 + md5[:8] 哈希后缀）。
    """
    keys: set[tuple[str, str]] = set()
    for engine_rel, action_rel, names in BUNDLED_PAIRS:
        engine_lines = _function_def_lines(
            (REPO_ROOT / engine_rel).read_text(encoding="utf-8"), names
        )
        action_lines = _function_def_lines(
            (REPO_ROOT / action_rel).read_text(encoding="utf-8"), names
        )
        for name in names:
            # 函数被改名/删除时立即失败（推导不出 = 无法对账）
            assert name in engine_lines, f"{engine_rel} 缺少函数 {name}（改名请同步 suppress.json）"
            assert name in action_lines, f"{action_rel} 缺少函数 {name}（改名请同步 suppress.json）"
            a_loc = f"{action_rel}::L{action_lines[name]} <-> {engine_rel}::L{engine_lines[name]}"
            b_loc = f"{engine_rel}::L{engine_lines[name]} <-> {action_rel}::L{action_lines[name]}"
            keys.add((RULE_ID, sanitize_structured_field(a_loc)))
            keys.add((RULE_ID, sanitize_structured_field(b_loc)))
    return keys


class TestBundledCopySuppressionDriftGuard:
    def test_suppressions_cover_live_derived_keys(self) -> None:
        """正向：实时推导的抑制 key 必须全部已登记（行漂移/改名即失败）。"""
        registered = {
            (s.get("rule_id"), s.get("location"))
            for s in load_suppressions(REPO_ROOT)
            if s.get("rule_id") == RULE_ID
        }
        expected = _expected_suppression_keys()
        missing = expected - registered
        assert not missing, (
            "CODE_HYGIENE_DUPLICATE_BLOCK 抑制条目与实时源码失配（函数行号漂移或改名）："
            f"{sorted(missing)}——请同步更新 .evolution/suppress.json 与 "
            "tests/test_evolution_scanner.py 的 expected 集合"
        )

    def test_no_stale_bundled_copy_suppressions(self) -> None:
        """反向：登记的 DUPLICATE_BLOCK 条目不得超出实时推导集（防失效残留）。"""
        registered = {
            (s.get("rule_id"), s.get("location"))
            for s in load_suppressions(REPO_ROOT)
            if s.get("rule_id") == RULE_ID
        }
        expected = _expected_suppression_keys()
        stale = registered - expected
        assert not stale, (
            f"发现失效的 DUPLICATE_BLOCK 抑制条目（源码已变，条目残留）: {sorted(stale)}"
        )
