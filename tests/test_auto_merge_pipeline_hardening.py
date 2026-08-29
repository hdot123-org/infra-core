"""auto-merge-pipeline.yml 硬化不变量测试（M4 gate-watchdog-automerge）

memory-core 的 test_auto_merge_triage.py 曾在 auto-merge.yml（内联形态）上
锁定 INFRA-416/428 两轮硬化不变量。M4 切换后执行体迁入本仓 auto-merge-pipeline.yml
（reusable），硬化 pin 随之迁移到本文件——在 reusable 载体上逐条锁定，
防止切换过程中弱化或丢失：

- VAL-T416-001/002 + VAL-428-003：CONFLICTING 通知 sentinel 幂等 + 去重命中 exit 0
- VAL-T416-003：triage NotFound → skip（竞态守卫）
- VAL-T416-004：mergeable=UNKNOWN 重取一次
- VAL-T416-006：job timeout-minutes: 10
- VAL-428-002g：triage 取数含 isDraft + statusCheckRollup（early-fire 防护）
- VAL-428-004：update-branch 失败降级绿腿（竞态守卫）
- VAL-428-005：stalled 类别 + head SHA sentinel + stalled 标志输出/消费
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_PATH = REPO_ROOT / ".github/workflows/auto-merge-pipeline.yml"


def _load() -> dict[str, Any]:
    doc = yaml.safe_load(PIPELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "auto-merge-pipeline.yml 必须是 YAML mapping"
    return doc


def _step(data: dict[str, Any], name: str) -> dict[str, Any]:
    steps = data["jobs"]["auto-merge"]["steps"]
    return next(s for s in steps if s.get("name") == name)


class TestNotifyStepIdempotency:
    """VAL-T416-001/002 + VAL-428-003：CONFLICTING 通知幂等。"""

    def test_notify_step_has_sentinel_dedup(self) -> None:
        """notify 步骤按 head SHA sentinel 去重评论，且查询既有评论/head SHA。"""
        run_block = _step(_load(), "Handle CONFLICTING PR (notify)")["run"]
        assert "auto-merge-conflict-" in run_block, (
            "notify 步骤必须包含 head SHA sentinel（幂等去重）"
        )
        assert "--json comments" in run_block or "--json headRefOid" in run_block, (
            "notify 步骤必须查询既有评论/head SHA"
        )

    def test_notify_skip_branch_does_not_comment(self) -> None:
        """已有同 SHA sentinel 时跳过评论：去重分支在 gh pr comment 之前短路。"""
        run_block = _step(_load(), "Handle CONFLICTING PR (notify)")["run"]
        assert "Skipping duplicate notification" in run_block, (
            "去重命中分支必须显式跳过且不调 gh pr comment"
        )
        assert run_block.index("Skipping duplicate notification") < run_block.index("gh pr comment")

    def test_notify_dedup_hit_exits_zero(self) -> None:
        """去重命中分支必须 exit 0（通知已送达=职责完成），否则未解决冲突每轮永久红腿。"""
        run_block = _step(_load(), "Handle CONFLICTING PR (notify)")["run"]
        segment = run_block.split("Skipping duplicate notification", 1)[1]
        segment_before_comment = segment.split("gh pr comment", 1)[0]
        assert "exit 0" in segment_before_comment
        assert "exit 1" not in segment_before_comment


class TestTriageStepHardening:
    """VAL-T416-003/004 + VAL-428-002g/005c：triage 步骤硬化。"""

    def test_triage_step_handles_pr_not_found(self) -> None:
        """PR 被并行腿合并后 gh pr view NotFound → skip 而非红腿。"""
        run_block = _step(_load(), "Triage PR mergeable state")["run"]
        assert "not found" in run_block or "Could not resolve" in run_block, (
            "triage 步骤必须识别 NotFound 并降级 skip（竞态守卫）"
        )
        assert "action=skip" in run_block

    def test_triage_step_retries_unknown_state(self) -> None:
        """mergeable=UNKNOWN 时等待重取一次，仍未知交 schedule 兜底。"""
        run_block = _step(_load(), "Triage PR mergeable state")["run"]
        assert '"$MERGEABLE" = "UNKNOWN"' in run_block, "triage 步骤必须对 UNKNOWN 状态做一次重取"
        assert "UNKNOWN retry" in run_block

    def test_workflow_triage_fetches_rollup_and_draft(self) -> None:
        """取数必须包含 isDraft + statusCheckRollup（early-fire/draft 盲合并防护）。"""
        triage_run = _step(_load(), "Triage PR mergeable state")["run"]
        fetch_line = next(
            (ln for ln in triage_run.splitlines() if "--json" in ln and "gh pr view" in ln),
            None,
        )
        assert fetch_line is not None, "triage 步骤未找到 gh pr view --json 取数行"
        assert "statusCheckRollup" in fetch_line, (
            "取数缺少 statusCheckRollup（early-fire 防护失效）"
        )
        assert "isDraft" in fetch_line, "取数缺少 isDraft（draft 盲合并防护失效）"

    def test_triage_outputs_stalled_flag(self) -> None:
        """triage 步骤输出 stalled 标志供 stalled 步骤门控。"""
        triage_run = _step(_load(), "Triage PR mergeable state")["run"]
        assert "stalled=" in triage_run, "triage 步骤未输出 stalled 标志"


class TestStalledStep:
    """VAL-428-005：stalled 处理步骤存在且幂等。"""

    def test_workflow_has_stalled_step_with_sentinel(self) -> None:
        data = _load()
        steps = data["jobs"]["auto-merge"]["steps"]
        stalled_step = next(
            (s for s in steps if "stalled" in str(s.get("name", "")).lower()),
            None,
        )
        assert stalled_step is not None, "缺少 stalled 处理步骤"
        run_block = stalled_step["run"]
        assert "auto-merge-stalled-" in run_block, "stalled 步骤必须按 head SHA sentinel 幂等"
        assert "gh pr comment" in run_block

    def test_stalled_step_consumes_flag(self) -> None:
        """stalled 步骤的 if 条件必须消费 triage 的 stalled 标志。"""
        data = _load()
        steps = data["jobs"]["auto-merge"]["steps"]
        stalled_step = next(s for s in steps if "stalled" in str(s.get("name", "")).lower())
        assert "steps.triage.outputs.stalled" in str(stalled_step.get("if", ""))


class TestUpdateBranchRaceGuard:
    """VAL-428-004：update-branch 失败降级绿腿（并行腿竞态正常收敛）。"""

    def test_update_branch_race_guard(self) -> None:
        run_block = _step(_load(), "Handle BEHIND PR (update-branch self-heal)")["run"]
        assert "if ! gh pr update-branch" in run_block or (
            "gh pr update-branch" in run_block and "exit 0" in run_block
        ), "update-branch 必须有失败降级分支（竞态守卫），不允许裸 exit 1"


class TestJobBounds:
    """VAL-T416-006：单腿时长限定，防 gh/网络挂死堆叠。"""

    def test_auto_merge_job_has_timeout(self) -> None:
        assert _load()["jobs"]["auto-merge"].get("timeout-minutes") == 10

    def test_matrix_bounds(self) -> None:
        strategy = _load()["jobs"]["auto-merge"]["strategy"]
        assert strategy["max-parallel"] == 5
        assert strategy["fail-fast"] is False
