"""Droid Autofix notify-only failure filter 契约测试（R1 — VAL-AF-001 / VAL-AF-002）。

锁定 droid-autofix.yml 上下文采集后新增的 notify 过滤步：
- VAL-AF-001: 步骤存在、id 正确、取失败 job 清单并精确匹配 notify job 名
- VAL-AF-002: 结构断言 + actionlint 零告警 + 既有 autofix 契约测试零回归

场景：
- 全部失败 job = "Notify CI complete to webhook gateway" → skip=true
- 混合失败（含非 notify job）→ 不 skip，正常接管
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTOFIX_YML = REPO_ROOT / ".github" / "workflows" / "droid-autofix.yml"

NOTIFY_JOB_NAME = "Notify CI complete to webhook gateway"


def _load() -> dict:
    """Load YAML, handling the on: → True pitfall."""
    data = yaml.safe_load(AUTOFIX_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "droid-autofix.yml must parse to a mapping"
    return data


def _steps() -> list[dict]:
    return _load()["jobs"]["autofix"]["steps"]


def _step_by_id(step_id: str) -> dict:
    for s in _steps():
        if s.get("id") == step_id:
            return s
    raise AssertionError(f"step id={step_id!r} not found")


def _step_names() -> list[str]:
    return [s.get("name", "") for s in _steps()]


# ── VAL-AF-001: skip 步骤在位 ────────────────────────────────────────


class TestNotifyFilterStepExists:
    """VAL-AF-001: 过滤步骤存在、id 正确、位于上下文采集之后。"""

    def test_filter_step_exists_with_correct_id(self):
        """notify_filter 步骤必须存在且 id=notify_filter。"""
        step = _step_by_id("notify_filter")
        assert step["id"] == "notify_filter"

    def test_filter_step_after_context_resolution(self):
        """过滤步必须在 Resolve PR context 之后、Attempt cap guard 之前。"""
        names = _step_names()
        ctx_idx = next(i for i, n in enumerate(names) if "Resolve PR context" in n)
        filter_idx = next(i for i, n in enumerate(names) if "Filter notify-only" in n)
        cap_idx = next(i for i, n in enumerate(names) if "Attempt cap guard" in n)
        assert ctx_idx < filter_idx < cap_idx, (
            f"order drift: ctx={ctx_idx}, filter={filter_idx}, cap={cap_idx}"
        )

    def test_filter_step_checks_ctx_skip(self):
        """过滤步自身必须受 ctx skip 短路（ctx 已决定 skip 就不需要再查 jobs）。"""
        step = _step_by_id("notify_filter")
        assert "steps.ctx.outputs.skip" in (step.get("if") or ""), (
            "filter step must check steps.ctx.outputs.skip"
        )

    def test_filter_script_uses_gh_run_view_json_jobs(self):
        """脚本必须用 gh run view --json jobs 取失败 job 清单。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        assert "gh run view" in script, "must use gh run view"
        assert "--json jobs" in script, "must use --json jobs"

    def test_filter_script_matches_exact_notify_job_name(self):
        """脚本必须精确匹配 'Notify CI complete to webhook gateway' job 名。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        assert NOTIFY_JOB_NAME in script, (
            f"filter script must match exact job name {NOTIFY_JOB_NAME!r}"
        )

    def test_filter_script_outputs_skip_true(self):
        """全部失败 job 为 notify 时，必须输出 skip=true。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        assert "skip=true" in script, "must output skip=true when all failures are notify"

    def test_filter_step_posts_pr_comment_on_skip(self):
        """skip 路径必须在 PR 评论注明基础设施送达失败、非代码问题。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        assert "gh pr comment" in script, "must post PR comment on skip"
        assert "非代码问题" in script or "autofix 不接管" in script, (
            "comment must note infrastructure failure / autofix not taking over"
        )

    def test_cap_step_also_checks_notify_filter_skip(self):
        """下游 cap 步骤必须同时检查 notify_filter 的 skip 输出。"""
        cap = _step_by_id("cap")
        cond = cap.get("if") or ""
        assert "notify_filter" in cond and "skip" in cond, (
            "cap step must short-circuit when notify_filter sets skip=true"
        )


class TestNotifyFilterSemantics:
    """VAL-AF-002: 仅 notify 失败 → skip；混合失败 → 接管。"""

    def test_script_counts_non_notify_failures(self):
        """脚本必须计算非 notify 失败 job 数量（混合失败判定依据）。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        # 必须有 jq 统计非 notify 失败
        assert "jq" in script and "length" in script, "must use jq to count non-notify failures"
        # 必须有 NON_NOTIFY 或类似变量
        assert "NON_NOTIFY" in script or "non_notify" in script.lower(), (
            "must compute non-notify failure count"
        )

    def test_script_decides_skip_when_all_notify(self):
        """全部失败 job 为 notify → skip=true；混合 → 不 skip。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        # 条件判定：NON_NOTIFY == 0 且 TOTAL > 0 → skip
        assert "NON_NOTIFY" in script and "-eq 0" in script, (
            "must skip when all failures are notify (NON_NOTIFY == 0)"
        )
        assert "TOTAL" in script and "-gt 0" in script, "must guard against empty failure list"

    def test_script_does_not_skip_on_mixed_failures(self):
        """混合失败（含非 notify）→ 不输出 skip，正常接管。"""
        step = _step_by_id("notify_filter")
        script = step["run"]
        # else 分支必须有明确日志
        assert "else" in script, "must have else branch for mixed failures"
        # 混合失败路径不应输出 skip=true（只有 notify-only 路径输出）
        # 验证：skip=true 只在 if 条件内
        lines = script.splitlines()
        skip_line_idx = next((i for i, line in enumerate(lines) if "skip=true" in line), None)
        assert skip_line_idx is not None, "must output skip=true somewhere"
        # skip=true 之前必须有 NON_NOTIFY == 0 条件
        preceding = "\n".join(lines[:skip_line_idx])
        assert "NON_NOTIFY" in preceding and "-eq 0" in preceding, (
            "skip=true must only be output when NON_NOTIFY == 0"
        )
