"""droid-review-watchdog quota-sweep 自愈结构测试（2026-08-19 PR #852）。

回归保护：BYOK 429 配额耗尽自愈（quota-sweep job）的关键属性。
背景：PR #850 实证 Bailian 配额打穿时 review exit 1，job log 只有
无差别 "exited with code 1"，真实 429 签名只在 debug artifact 的
session transcript 里；且配额未恢复时立即 rerun 无意义。quota-sweep
以 schedule 扫描 + artifact 检测 + 恢复窗口 + attempt 限界实现自愈。

这些断言防止自愈逻辑被静默移除或弱化（如去掉恢复窗口导致 rerun
风暴、去掉 attempt 限界导致无限重试）。
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).parent.parent
WATCHDOG_PATH = REPO_ROOT / ".github/workflows/droid-review-watchdog.yml"


def _load() -> dict:
    return yaml.safe_load(WATCHDOG_PATH.read_text())


def _quota_sweep_run() -> str:
    data = _load()
    steps = data["jobs"]["quota-sweep"]["steps"]
    return steps[0]["run"]


class TestQuotaSweepJobStructure:
    """quota-sweep job 的存在性与触发配置。

    M2 HOTFIX: 触发器全部禁用为 workflow_dispatch-only 桩。
    以下测试适配 dispatch-only 形态，M4 reusable/caller 重写时更新。
    """

    def test_quota_sweep_job_exists(self):
        """quota-sweep job 必须存在（429 自愈入口）。"""
        assert "quota-sweep" in _load()["jobs"]

    def test_dispatch_only_trigger(self):
        """M2 HOTFIX: 触发器禁用为 workflow_dispatch only。"""
        on_block = _load()[True]  # yaml 把 `on:` 解析为 True
        assert "workflow_dispatch" in on_block
        # schedule 和 workflow_run 不应存在（HOTFIX 移除）
        assert "schedule" not in on_block
        assert "workflow_run" not in on_block

    def test_quota_sweep_gated_on_schedule_event(self):
        """quota-sweep 的 if: 条件保留（M4 恢复 schedule 时直接生效）。"""
        assert _load()["jobs"]["quota-sweep"]["if"] == "github.event_name == 'schedule'"

    def test_quota_sweep_unreachable_state_locked(self):
        """锁定 quota-sweep 当前不可达状态（M2 HOTFIX → M4 恢复）。

        当前触发器已禁用为 workflow_dispatch-only，quota-sweep job 的
        if: github.event_name == 'schedule' 条件永不为真（workflow_dispatch
        触发时 event_name 不是 schedule）。

        本测试锁定这一事实：
        1. workflow 触发器不含 schedule（已被 HOTFIX 移除）
        2. quota-sweep job 的 if 条件仍保留（M4 恢复 schedule 时自动生效）
        3. 状态不可达（dispatch-only 触发器 + schedule 守卫 = 永假分支）

        M4 恢复路径：在 .github/workflows/droid-review-watchdog.yml 的
        on: 块中添加 schedule 触发器，本测试会自动失败提醒更新。
        """
        data = _load()
        on_block = data[True]  # yaml 把 `on:` 解析为 True

        # 触发器不含 schedule（HOTFIX 已移除）
        assert "schedule" not in on_block, "schedule 触发器不应存在（M2 HOTFIX 已移除）"

        # quota-sweep job 的 if 条件保留
        quota_sweep_job = data["jobs"]["quota-sweep"]
        assert quota_sweep_job["if"] == "github.event_name == 'schedule'"

        # 验证状态不可达：dispatch-only 触发器 + schedule 守卫 = 永假分支
        # 这是预期状态（M2 HOTFIX），M4 恢复 schedule 时本测试会失败提醒更新
        assert "workflow_dispatch" in on_block, "workflow_dispatch 触发器必须保留"

    def test_contract_name_preserved(self):
        """M2 HOTFIX: workflow name 契约字符串保留。"""
        assert _load()["name"] == "Droid Review Watchdog"


class TestQuotaSweepDetectionLogic:
    """429 检测与防风暴关键属性。"""

    def test_artifact_signature_grep(self):
        """检测必须 grep transcript 的 quota exceeded 签名（job log 无此特征）。"""
        run = _quota_sweep_run()
        assert "quota exceeded" in run
        assert ".factory/sessions/" in run

    def test_recovery_window_uses_vars(self):
        """恢复窗口通过 QUOTA_RECOVERY_WINDOW_SECONDS 变量配置（默认 1800s）。"""
        run = _quota_sweep_run()
        # 变量引用
        assert "QUOTA_RECOVERY_WINDOW_SECONDS" in run
        # 默认值回退
        assert "1800" in run
        # 使用变量而非硬编码
        assert (
            '-lt "$QUOTA_RECOVERY_WINDOW_SECONDS"' in run
            or "-lt ${QUOTA_RECOVERY_WINDOW_SECONDS}" in run
        )

    def test_attempt_limit_uses_vars(self):
        """run_attempt 限界通过 WATCHDOG_MAX_ATTEMPT 变量配置（默认 3）。"""
        run = _quota_sweep_run()
        # 变量引用
        assert "WATCHDOG_MAX_ATTEMPT" in run
        # 默认值回退
        assert "3" in run

    def test_rerun_uses_failed_jobs_api(self):
        """rerun 必须走 rerun-failed-jobs API（终态 run 才可用）。"""
        run = _quota_sweep_run()
        assert "rerun-failed-jobs" in run

    def test_scan_window_uses_vars(self):
        """扫描窗口通过 QUOTA_SCAN_WINDOW_HOURS 变量配置（默认 6 小时）。"""
        run = _quota_sweep_run()
        # 变量引用
        assert "QUOTA_SCAN_WINDOW_HOURS" in run
        # 默认值回退
        assert "6 hours ago" in run or "QUOTA_SCAN_WINDOW_HOURS" in run
        # 使用变量构造时间范围
        assert "hours ago" in run

    def test_fail_closed_no_conclusion_change(self):
        """门禁语义：脚本只请求 rerun，不写 check 结论、不绕过门禁。"""
        run = _quota_sweep_run()
        # 不存在任何 check 结论改写 API
        for forbidden in ("check-runs", "annotations", "--admin"):
            assert forbidden not in run


class TestExistingJobsPreserved:
    """原有 watchdog 职责不受影响。"""

    def test_self_heal_rerun_preserved(self):
        """self-heal-rerun（503 自愈）保留且限界通过 WATCHDOG_MAX_ATTEMPT 变量配置。"""
        data = _load()
        assert "self-heal-rerun" in data["jobs"]
        # run_attempt 限界已从 if: 移到 shell run block（通过 WATCHDOG_MAX_ATTEMPT 变量）
        job = data["jobs"]["self-heal-rerun"]
        run_block = job["steps"][0]["run"]
        assert "WATCHDOG_MAX_ATTEMPT" in run_block
        assert "MAX_ATTEMPT" in run_block

    def test_cancel_on_ci_fail_preserved(self):
        """cancel-on-ci-fail（CI 红取消烧钱 review）保留。"""
        assert "cancel-on-ci-fail" in _load()["jobs"]

    def test_timeout_minutes_bounded(self):
        """quota-sweep 有 timeout 上界（防 sweep 自身挂死）。"""
        assert _load()["jobs"]["quota-sweep"]["timeout-minutes"] <= 15
