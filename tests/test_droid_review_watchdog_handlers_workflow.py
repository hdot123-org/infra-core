"""droid-review-watchdog-handlers reusable workflow 契约测试（M4 gate-watchdog-automerge）

锁定 memory-core watchdog thin caller（VAL-GATE-107）所依赖的 reusable workflow
不变量：
- workflow_call 触发面：inputs（mode / run_id / run_attempt / head_sha / max_attempt，M5 R1(3) snake_case）
- mode 门控：self-heal-rerun / cancel-on-ci-fail 两 job 各按 inputs.mode 精确选择
- 本文件不引用具体 workflow 名（事件守卫由 caller 承载，防双份守卫漂移）
- 503 特征表 / rerun-failed-jobs / attempt 限界 / cancel 过滤逻辑与原内联实现等价
- 零 checkout（self-hosted 共享工作区防毒铁律）+ runs-on [self-hosted, pve-linux]
- 门禁语义：只请求 rerun / cancel，绝不携带 merge/--admin/--force

quota-sweep 的 artifact 前缀过滤契约（droid-review-debug-）不在本文件——
按 VAL-GATE-107 留在 caller 文件断言。
"""

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/droid-review-watchdog-handlers.yml"


@pytest.fixture(scope="module")
def handlers_data() -> dict:
    data = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert data is not None, "droid-review-watchdog-handlers.yml missing or empty"
    return data


@pytest.fixture(scope="module")
def workflow_call(handlers_data) -> dict:
    triggers = handlers_data.get(True, {}) or handlers_data.get("on", {})
    assert "workflow_call" in triggers, "必须声明 workflow_call 触发器"
    return triggers["workflow_call"]


def _handler_step(handlers_data: dict, job: str, keyword: str) -> dict:
    steps = handlers_data["jobs"][job]["steps"]
    return next(s for s in steps if keyword in s.get("name", "").lower())


class TestWorkflowCallSurface:
    """workflow_call inputs 契约（thin caller 的调用面）"""

    def test_inputs_declared(self, workflow_call):
        inputs = workflow_call.get("inputs", {})
        for name in ("mode", "run_id", "run_attempt", "head_sha", "max_attempt"):
            assert name in inputs, f"workflow_call 缺少 input: {name}"

    def test_mode_required_string(self, workflow_call):
        mode = workflow_call["inputs"]["mode"]
        assert mode["required"] is True, "mode 必填（选择 handler 的唯一开关）"
        assert mode["type"] == "string"

    def test_run_id_and_attempt_are_numbers(self, workflow_call):
        assert workflow_call["inputs"]["run_id"]["type"] == "number"
        assert workflow_call["inputs"]["run_attempt"]["type"] == "number"
        assert workflow_call["inputs"]["run_id"]["required"] is True
        assert workflow_call["inputs"]["run_attempt"]["required"] is True

    def test_optional_inputs_have_empty_defaults(self, workflow_call):
        """head_sha / max_attempt 可选且默认空串（脚本内 -z 回退兜底）"""
        for name in ("head_sha", "max_attempt"):
            inp = workflow_call["inputs"][name]
            assert inp["required"] is False, f"{name} 必须可选"
            assert inp["default"] == "", f"{name} 默认必须为空串"


class TestModeGatedJobs:
    """mode 门控：caller 守卫求值后，本文件按 mode 精确选择 handler"""

    def test_exactly_two_handler_jobs(self, handlers_data):
        jobs = set(handlers_data["jobs"].keys())
        assert jobs == {"self-heal-rerun", "cancel-on-ci-fail"}, (
            f"必须恰好两个 handler job，实际: {jobs}"
        )

    def test_no_workflow_name_references(self, handlers_data):
        """事件守卫归 caller：本文件不得出现具体 workflow 名比较（防双份守卫漂移）"""
        raw = WORKFLOW_PATH.read_text()
        for guarded_expr in (
            "workflow_run.name ==",
            "event_name == 'schedule'",
            "github.event.workflow_run.conclusion ==",
        ):
            assert guarded_expr not in raw, (
                f"事件守卫必须留在 caller 文件，本文件出现: {guarded_expr}"
            )

    def test_self_heal_gated_by_mode(self, handlers_data):
        job_if = str(handlers_data["jobs"]["self-heal-rerun"].get("if", ""))
        assert job_if.strip() == "inputs.mode == 'self-heal-rerun'"

    def test_cancel_gated_by_mode(self, handlers_data):
        job_if = str(handlers_data["jobs"]["cancel-on-ci-fail"].get("if", ""))
        assert job_if.strip() == "inputs.mode == 'cancel-on-ci-fail'"


class TestSelfHealHandlerBody:
    """503 自愈 rerun 执行体契约（与 memory-core 原内联实现行为等价）"""

    def test_bounded_run_attempt_with_z_fallback(self, handlers_data):
        """run_attempt 限界 + -z 判断回退（VAL-VARS-004 良性模式，非 :- 死代码）"""
        run_block = _handler_step(handlers_data, "self-heal-rerun", "rerun")["run"]
        assert "MAX_ATTEMPT" in run_block
        assert 'if [ -z "${MAX_ATTEMPT:-}" ]' in run_block
        import re

        assert not re.search(
            r'MAX_ATTEMPT="\$\{MAX_ATTEMPT:-3\}"\s*\n\s*if\s+\[\s+-z', run_block
        ), "MAX_ATTEMPT 仍有 :-3 死代码模式"

    def test_503_patterns_only(self, handlers_data):
        """特征表只含 infra 瞬时错误（2026-08-17/18 实测根因）"""
        run_block = _handler_step(handlers_data, "self-heal-rerun", "rerun")["run"]
        assert "permission - 503" in run_block
        assert "Failed to check permissions" in run_block
        assert "HttpError: No server is currently available" in run_block
        assert "unexpected EOF" in run_block
        assert "TLS handshake timeout" in run_block

    def test_rerun_request_fail_open_warning(self, handlers_data):
        """fail-closed 门禁语义：rerun 请求失败只 warning，不绕过门禁"""
        run_block = _handler_step(handlers_data, "self-heal-rerun", "rerun")["run"]
        assert "rerun-failed-jobs" in run_block
        assert "::warning::" in run_block

    def test_no_gate_bypass_tokens(self, handlers_data):
        run_block = _handler_step(handlers_data, "self-heal-rerun", "rerun")["run"]
        for forbidden in ("--admin", "--force", "merge"):
            assert forbidden not in run_block, f"forbidden token in self-heal: {forbidden}"

    def test_env_wired_from_inputs(self, handlers_data):
        env = _handler_step(handlers_data, "self-heal-rerun", "rerun").get("env", {})
        assert env["RUN_ID"] == "${{ inputs.run_id }}"
        assert env["RUN_ATTEMPT"] == "${{ inputs.run_attempt }}"
        assert env["MAX_ATTEMPT"] == "${{ inputs.max_attempt }}"


class TestCancelOnCiFailHandlerBody:
    """cancel-on-ci-fail 执行体契约（与 memory-core 原内联实现行为等价）"""

    def test_cancels_only_review_runs_by_head_sha(self, handlers_data):
        """取消目标按 name == Droid Auto Review 过滤 + head_sha 定位"""
        run_block = _handler_step(handlers_data, "cancel-on-ci-fail", "cancel")["run"]
        assert "Droid Auto Review" in run_block
        assert "head_sha" in run_block
        assert "/cancel" in run_block

    def test_cancel_failure_warning_only(self, handlers_data):
        run_block = _handler_step(handlers_data, "cancel-on-ci-fail", "cancel")["run"]
        assert "::warning::" in run_block

    def test_no_gate_bypass_tokens(self, handlers_data):
        run_block = _handler_step(handlers_data, "cancel-on-ci-fail", "cancel")["run"]
        for forbidden in ("--admin", "--force", " merge"):
            assert forbidden not in run_block, f"forbidden token in cancel job: {forbidden}"

    def test_env_wired_from_inputs(self, handlers_data):
        env = _handler_step(handlers_data, "cancel-on-ci-fail", "cancel").get("env", {})
        assert env["HEAD_SHA"] == "${{ inputs.head_sha }}"


class TestSelfHostedSafety:
    """runner 铁律 + 共享工作区防毒（2026-08-26/28 双铁律）"""

    def test_all_jobs_self_hosted(self, handlers_data):
        for job_name, job in handlers_data["jobs"].items():
            assert job.get("runs-on") == ["self-hosted", "pve-linux"], (
                f"{job_name} 必须跑自建 runner（禁止 ubuntu-latest）"
            )

    def test_no_checkout_anywhere(self, handlers_data):
        """纯 gh API handler：任何 job 都不得 checkout（共享持久工作区防毒）"""
        for job_name, job in handlers_data["jobs"].items():
            for step in job.get("steps") or []:
                uses = str(step.get("uses", ""))
                assert not uses.startswith("actions/checkout"), (
                    f"{job_name}: handler job 禁止 actions/checkout（零工作区足迹）"
                )

    def test_timeouts_preserved(self, handlers_data):
        assert handlers_data["jobs"]["self-heal-rerun"]["timeout-minutes"] == 10
        assert handlers_data["jobs"]["cancel-on-ci-fail"]["timeout-minutes"] == 5

    def test_permissions_actions_write_only(self, handlers_data):
        perms = handlers_data.get("permissions", {})
        assert perms.get("actions") == "write"
        assert "contents" not in perms, "权限最小化：handler 只需 actions: write"
