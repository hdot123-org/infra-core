"""Droid Task Executor 契约测试（R1 mission — VAL-EX-001 ~ VAL-EX-007）。

覆盖 unified-executor feature 的全部验证断言：
- VAL-EX-001: droid-task.yml 触发类型/runs-on/timeout
- VAL-EX-002: 单飞并发护栏（concurrency group + cancel-in-progress: false）
- VAL-EX-003: composite setup-droid-byok 存在且 BYOK-only
- VAL-EX-004: prompt 模板移植完整（error-gateway Issue-first + linear-gateway Fixes REF）
- VAL-EX-005: if:failure() 兜底建 Issue
- VAL-EX-006: dry-run 闭环（由 gh workflow run 验证，本文件锁定结构前提）
- VAL-EX-007: 回归绿（本测试文件本身是回归基线的一部分）
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "droid-task.yml"
COMPOSITE_DIR = REPO_ROOT / ".github" / "actions" / "setup-droid-byok"
COMPOSITE = COMPOSITE_DIR / "action.yml"


def _load(path: Path) -> dict:
    """Load YAML, handling the on: → True pitfall."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} must parse to a mapping"
    return data


def _triggers(data: dict) -> dict:
    """YAML 1.1 parses bare 'on' as boolean True."""
    return data.get("on") or data.get(True) or {}


def _steps_by_name(steps: list[dict]) -> dict[str, dict]:
    """Index steps by name for easy lookup."""
    return {s.get("name", ""): s for s in steps}


# ── VAL-EX-001: 触发类型/runs-on/timeout ──────────────────────────────


class TestTriggerAndRunSurface:
    """VAL-EX-001: droid-task.yml 触发与运行面正确。"""

    def test_trigger_is_repository_dispatch_droid_task(self):
        """on: repository_dispatch: types: [droid-task]"""
        triggers = _triggers(_load(WORKFLOW))
        assert "repository_dispatch" in triggers, (
            "droid-task.yml must trigger on repository_dispatch"
        )
        rd = triggers["repository_dispatch"]
        assert rd is not None
        types = rd.get("types", [])
        assert "droid-task" in types, (
            f"repository_dispatch types must include 'droid-task', got {types}"
        )

    def test_runs_on_self_hosted_pve_linux(self):
        """runs-on: [self-hosted, pve-linux]"""
        data = _load(WORKFLOW)
        job = data["jobs"]["execute"]
        assert job["runs-on"] == ["self-hosted", "pve-linux"], (
            f"runs-on must be [self-hosted, pve-linux], got {job['runs-on']}"
        )

    def test_timeout_minutes_60(self):
        """timeout-minutes: 60"""
        data = _load(WORKFLOW)
        job = data["jobs"]["execute"]
        assert job["timeout-minutes"] == 60, (
            f"timeout-minutes must be 60, got {job['timeout-minutes']}"
        )


# ── VAL-EX-002: 并发护栏 ──────────────────────────────────────────────


class TestConcurrencyGuard:
    """VAL-EX-002: 单飞并发护栏在位。"""

    def test_concurrency_group_uses_task_id(self):
        """concurrency.group: droid-task-${{ github.event.client_payload.task_id }}"""
        data = _load(WORKFLOW)
        conc = data.get("concurrency")
        assert conc is not None, "droid-task.yml must have top-level concurrency"
        group = conc.get("group", "")
        assert "droid-task-" in group, f"concurrency group must contain 'droid-task-', got: {group}"
        assert "task_id" in group, f"concurrency group must reference task_id, got: {group}"

    def test_cancel_in_progress_is_false(self):
        """cancel-in-progress: false（不取消正在运行的同 task）"""
        data = _load(WORKFLOW)
        conc = data["concurrency"]
        assert conc.get("cancel-in-progress") is False, (
            f"cancel-in-progress must be false, got {conc.get('cancel-in-progress')}"
        )


# ── VAL-EX-003: composite BYOK-only ──────────────────────────────────


class TestCompositeByokOnly:
    """VAL-EX-003: composite setup-droid-byok 存在且 BYOK-only。"""

    def test_composite_action_file_exists(self):
        """.github/actions/setup-droid-byok/action.yml 存在"""
        assert COMPOSITE.exists(), f"Composite action must exist at {COMPOSITE}"

    def test_composite_uses_inputs_not_secrets(self):
        """composite 内不得直接引用 secrets.*，须经 inputs"""
        raw = COMPOSITE.read_text(encoding="utf-8")
        # 排除注释行后检查 secrets. 引用
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # 跳过行内注释部分
            code_part = line.split("#")[0] if "#" in line else line
            assert "secrets." not in code_part, (
                f"composite must not reference secrets.* directly (use inputs instead): {line.strip()}"
            )

    def test_composite_declares_bailian_api_key_input(self):
        """inputs.bailian-api-key 声明"""
        data = _load(COMPOSITE)
        inputs = data.get("inputs", {})
        assert "bailian-api-key" in inputs, "composite must declare bailian-api-key input"
        assert inputs["bailian-api-key"].get("required") is True

    def test_composite_is_composite_type(self):
        """runs.using: composite"""
        data = _load(COMPOSITE)
        assert data["runs"]["using"] == "composite"

    def test_composite_no_factory_credits_dependency(self):
        """VAL-EX-003: composite 无 factory_credits / FACTORY_API_KEY 依赖。

        允许出现在注释/描述/验证拒止逻辑中（BYOK-only 硬门禁本身提及 factoryCredits
        是为了拒绝它）；但 settings.json 生成逻辑（jq 段）不得含 factoryCredits 键，
        且不得引用 FACTORY_API_KEY 环境变量。
        """
        raw = COMPOSITE.read_text(encoding="utf-8")
        # 提取 jq 生成 settings.json 的代码块
        # jq 段从 "jq -n" 开始到 "'> \"$HOME/.factory/settings.json\"" 结束
        jq_block_lines = []
        in_jq = False
        for line in raw.splitlines():
            if "jq -n" in line:
                in_jq = True
            if in_jq:
                jq_block_lines.append(line)
            if in_jq and "settings.json" in line and ">" in line:
                break
        jq_block = "\n".join(jq_block_lines)
        # jq 生成块不得包含 factoryCredits 键（作为正向写入）
        assert "factoryCredits:" not in jq_block and '"factoryCredits"' not in jq_block, (
            "jq settings.json generation must NOT write factoryCredits key"
        )
        # 整个文件不得引用 FACTORY_API_KEY 环境变量
        assert "FACTORY_API_KEY" not in raw, (
            "composite must not reference FACTORY_API_KEY env var (BYOK-only铁律)"
        )

    def test_composite_writes_settings_json_with_custom_models(self):
        """jq 生成 settings.json 含 customModels 指向百炼 coding 端点"""
        raw = COMPOSITE.read_text(encoding="utf-8")
        assert "customModels" in raw, "composite must write customModels to settings.json"
        assert "coding.dashscope.aliyuncs.com" in raw, (
            "composite must point to Bailian coding endpoint"
        )

    def test_composite_has_byok_only_verification(self):
        """composite 内置 BYOK-only 硬门禁（确认 settings.json 无 factoryCredits）"""
        raw = COMPOSITE.read_text(encoding="utf-8")
        assert "factoryCredits" in raw, (
            "composite must have BYOK-only verification step (checking no factoryCredits)"
        )

    def test_composite_installs_droid_cli(self):
        """composite 安装 droid CLI"""
        raw = COMPOSITE.read_text(encoding="utf-8")
        assert "app.factory.ai/cli" in raw, "composite must install droid CLI from official source"
        assert "droid --version" in raw, "composite must verify droid installation"

    def test_workflow_uses_composite_action(self):
        """droid-task.yml 使用 ./.github/actions/setup-droid-byok"""
        data = _load(WORKFLOW)
        steps = data["jobs"]["execute"]["steps"]
        setup_steps = [
            s for s in steps if s.get("uses", "").startswith("./.github/actions/setup-droid-byok")
        ]
        assert len(setup_steps) == 1, (
            f"workflow must use setup-droid-byok composite exactly once, found {len(setup_steps)}"
        )
        # 验证传入 bailian-api-key
        setup_step = setup_steps[0]
        with_block = setup_step.get("with", {})
        assert "bailian-api-key" in with_block, (
            "setup-droid-byok must receive bailian-api-key input"
        )


# ── VAL-EX-004: prompt 模板移植完整 ───────────────────────────────────


class TestPromptTemplates:
    """VAL-EX-004: prompt 模板移植完整。"""

    def test_error_gateway_prompt_step_exists(self):
        """error-gateway prompt 步骤存在"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        assert "Build prompt (error-gateway)" in steps

    def test_error_gateway_prompt_has_issue_first_hard_gate(self):
        """error-gateway prompt 含 Issue-first 硬门禁关键词"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Build prompt (error-gateway)"]
        run = step["run"]
        # Issue-first 硬门禁关键句
        assert "Issue-first" in run or "Issue-first" in run, (
            "error-gateway prompt must contain Issue-first hard gate"
        )
        assert "posthog-error-sync" in run, (
            "error-gateway prompt must reference posthog-error-sync label"
        )
        assert "--state all" in run, (
            "error-gateway prompt must use --state all for idempotent check"
        )
        assert "Closes #" in run or "Fixes #" in run, (
            "error-gateway prompt must require Closes/Fixes #<issue-number>"
        )

    def test_error_gateway_prompt_condition(self):
        """error-gateway prompt 步骤条件正确"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Build prompt (error-gateway)"]
        condition = step.get("if", "")
        assert "error-gateway" in condition, (
            f"error-gateway prompt condition must reference error-gateway, got: {condition}"
        )

    def test_linear_gateway_prompt_step_exists(self):
        """linear-gateway prompt 步骤存在"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        assert "Build prompt (linear-gateway)" in steps

    def test_linear_gateway_prompt_has_fixes_ref(self):
        """linear-gateway prompt 含 Fixes REF 回写契约"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Build prompt (linear-gateway)"]
        run = step["run"]
        assert "Fixes" in run, "linear-gateway prompt must contain Fixes REF contract"
        assert "P_IDENTIFIER" in run, "linear-gateway prompt must reference issue identifier"

    def test_linear_gateway_prompt_has_gate_a_idempotency(self):
        """linear-gateway prompt 含 Gate A 幂等性检查"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Build prompt (linear-gateway)"]
        run = step["run"]
        assert "Gate A" in run or "幂等" in run or "completed" in run, (
            "linear-gateway prompt must include Gate A idempotency check"
        )

    def test_linear_gateway_prompt_condition(self):
        """linear-gateway prompt 步骤条件正确"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Build prompt (linear-gateway)"]
        condition = step.get("if", "")
        assert "linear-gateway" in condition, (
            f"linear-gateway prompt condition must reference linear-gateway, got: {condition}"
        )

    def test_prompt_uses_env_vars_not_inline_expressions(self):
        """prompt 步骤通过 env: 映射传值（不直接在 run 内用 ${{ }} 展开 payload）"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        for name in ("Build prompt (error-gateway)", "Build prompt (linear-gateway)"):
            step = steps[name]
            env = step.get("env", {})
            assert len(env) > 0, f"{name} must use env: mapping to pass payload values"


# ── VAL-EX-005: 失败兜底 ──────────────────────────────────────────────


class TestFailureFallback:
    """VAL-EX-005: if:failure() 建 Issue 兜底在位。"""

    def test_failure_fallback_step_exists(self):
        """Failure fallback 步骤存在"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        # 找到包含 failure fallback 的步骤
        fallback_steps = {
            k: v for k, v in steps.items() if "failure" in k.lower() or "fallback" in k.lower()
        }
        assert len(fallback_steps) >= 1, (
            f"workflow must have a failure fallback step, found steps: {list(steps.keys())}"
        )

    def test_failure_fallback_has_if_failure_condition(self):
        """failure fallback 步骤有 if: failure() 条件"""
        data = _load(WORKFLOW)
        steps = data["jobs"]["execute"]["steps"]
        fallback = [
            s
            for s in steps
            if "failure" in s.get("name", "").lower() or "fallback" in s.get("name", "").lower()
        ]
        assert len(fallback) >= 1
        step = fallback[0]
        condition = step.get("if", "")
        assert "failure()" in condition, (
            f"failure fallback must have if: failure() condition, got: {condition}"
        )

    def test_failure_fallback_creates_issue(self):
        """failure fallback 步骤使用 gh issue create"""
        data = _load(WORKFLOW)
        steps = data["jobs"]["execute"]["steps"]
        fallback = [
            s
            for s in steps
            if "failure" in s.get("name", "").lower() or "fallback" in s.get("name", "").lower()
        ]
        step = fallback[0]
        run = step["run"]
        assert "gh issue create" in run, "failure fallback must create GitHub Issue via gh CLI"

    def test_failure_fallback_has_needs_triage_label(self):
        """failure fallback 创建的 Issue 带 needs-triage label"""
        data = _load(WORKFLOW)
        steps = data["jobs"]["execute"]["steps"]
        fallback = [
            s
            for s in steps
            if "failure" in s.get("name", "").lower() or "fallback" in s.get("name", "").lower()
        ]
        step = fallback[0]
        run = step["run"]
        assert "needs-triage" in run, "failure fallback Issue must have needs-triage label"

    def test_failure_fallback_has_idempotent_check(self):
        """failure fallback 有幂等检查（避免重复创建 Issue）"""
        data = _load(WORKFLOW)
        steps = data["jobs"]["execute"]["steps"]
        fallback = [
            s
            for s in steps
            if "failure" in s.get("name", "").lower() or "fallback" in s.get("name", "").lower()
        ]
        step = fallback[0]
        run = step["run"]
        assert "gh issue list" in run, (
            "failure fallback must check for existing Issues before creating (idempotent)"
        )
        assert "--state all" in run, "failure fallback idempotent check must use --state all"


# ── VAL-EX-006: dry-run 结构前提 ──────────────────────────────────────


class TestDryRunPrerequisites:
    """VAL-EX-006: dry-run 闭环的结构前提（实际 dry-run 由 gh workflow run 验证）。"""

    def test_workflow_has_execute_step(self):
        """workflow 有 droid exec 执行步骤"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        assert "Execute droid" in steps, "workflow must have 'Execute droid' step"

    def test_execute_step_uses_auto_high(self):
        """droid exec 使用 --auto high 模式"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Execute droid"]
        run = step["run"]
        assert "--auto high" in run, "droid exec must use --auto high mode"

    def test_execute_step_uses_tag_metadata(self):
        """droid exec 使用 --tag 传递元数据"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Execute droid"]
        run = step["run"]
        assert "--tag" in run, "droid exec must pass --tag metadata"

    def test_workflow_permissions_include_contents_write(self):
        """workflow 顶层权限含 contents: write"""
        data = _load(WORKFLOW)
        perms = data.get("permissions", {})
        assert perms.get("contents") == "write", f"workflow must have contents: write, got {perms}"

    def test_workflow_permissions_include_issues_write(self):
        """workflow 顶层权限含 issues: write（失败兜底建 Issue 需要）"""
        data = _load(WORKFLOW)
        perms = data.get("permissions", {})
        assert perms.get("issues") == "write", (
            f"workflow must have issues: write (for failure fallback Issue), got {perms}"
        )

    def test_validate_payload_step_exists(self):
        """workflow 有 payload 验证步骤"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        assert "Validate payload" in steps, (
            "workflow must validate client_payload before processing"
        )

    def test_validate_payload_checks_required_fields(self):
        """payload 验证检查 kind/task_id/repo 三个必需字段"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Validate payload"]
        run = step["run"]
        assert "kind" in run
        assert "task_id" in run
        assert "repo" in run

    def test_validate_payload_rejects_invalid_kind(self):
        """payload 验证拒绝非法 kind 值"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        step = steps["Validate payload"]
        run = step["run"]
        assert "error-gateway" in run
        assert "linear-gateway" in run


# ── VAL-EX-007 基础：结构回归 ──────────────────────────────────────────


class TestWorkflowStructureRegression:
    """VAL-EX-007 基础：workflow 结构回归断言（全量 pytest + actionlint 由 CI 执行）。"""

    def test_workflow_name_is_descriptive(self):
        """workflow 名清晰表达用途"""
        data = _load(WORKFLOW)
        name = data.get("name", "")
        assert "Droid Task" in name or "droid" in name.lower(), (
            f"workflow name should be descriptive, got: {name}"
        )

    def test_workflow_file_has_header_comment(self):
        """workflow 文件有头注释说明设计依据"""
        raw = WORKFLOW.read_text(encoding="utf-8")
        assert "BYOK" in raw or "byok" in raw, "workflow file should mention BYOK in header or body"

    def test_self_checkout_step_exists_and_uses_dispatch_token(self):
        """Checkout executor host repo (self) 步骤存在且使用 DISPATCH_TOKEN"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        checkout = steps.get("Checkout executor host repo (self)", {})
        with_block = checkout.get("with", {})
        token = with_block.get("token", "")
        assert "DISPATCH_TOKEN" in token, f"self-checkout must use DISPATCH_TOKEN, got: {token}"

    def test_checkout_step_uses_dispatch_token(self):
        """checkout target repo 步骤使用 DISPATCH_TOKEN 凭证"""
        data = _load(WORKFLOW)
        steps = _steps_by_name(data["jobs"]["execute"]["steps"])
        checkout = steps.get("Checkout target repo", {})
        with_block = checkout.get("with", {})
        token = with_block.get("token", "")
        assert "DISPATCH_TOKEN" in token, f"checkout must use DISPATCH_TOKEN, got: {token}"

    def test_step_order_self_checkout_before_setup_before_target_checkout(self):
        """步骤顺序：Validate → Self checkout → Setup BYOK → Target checkout → Build prompt → Execute
        
        VAL-RTR-002 新语义（2026-09-10 用户裁定 U6）：执行面集中 infra-core，
        droid-task.yml 必须先 checkout 本仓（composite 可用）再 checkout 目标仓。
        """
        data = _load(WORKFLOW)
        names = [s.get("name", "") for s in data["jobs"]["execute"]["steps"]]
        # 核心断言：self-checkout → setup → target checkout 顺序
        assert names.index("Validate payload") < names.index("Checkout executor host repo (self)")
        assert names.index("Checkout executor host repo (self)") < names.index("Setup Droid BYOK")
        assert names.index("Setup Droid BYOK") < names.index("Checkout target repo")
        assert names.index("Checkout target repo") < names.index("Execute droid")

    def test_no_hardcoded_local_paths(self):
        """公开仓库不含本地绝对路径（/Users/... 等）"""
        raw = WORKFLOW.read_text(encoding="utf-8")
        assert "/Users/" not in raw, "workflow must not contain hardcoded local paths (/Users/...)"
        raw_composite = COMPOSITE.read_text(encoding="utf-8")
        assert "/Users/" not in raw_composite, (
            "composite must not contain hardcoded local paths (/Users/...)"
        )
