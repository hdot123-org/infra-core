"""命名契约测试（architecture.md §3）

这些字符串构成隐式契约网络，任何静默改动会杀死 auto-merge/watchdog。
infra-core 侧对 shipped workflow 模板断言字节级一致。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent

# 契约：workflow 名（auto-merge workflow_run 依赖）
CONTRACT_WORKFLOW_NAMES = {
    ".github/workflows/ci.yml": "CI",
    ".github/workflows/qa.yml": "QA",
    ".github/workflows/evolution-governance.yml": "Evolution Governance",
}

# 契约：governance 门禁 job 显示名（branch protection required check）
CONTRACT_GOVERNANCE_JOB_NAME = "Block non-owner governance modifications"

# 契约：ci-ok 聚合 job key（branch protection required check）
CONTRACT_CI_OK_JOB_KEY = "ci-ok"


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


class TestWorkflowNameContract:
    def test_ci_workflow_name(self):
        assert re.search(r"^name:\s*CI\s*$", _read(".github/workflows/ci.yml"), re.MULTILINE)

    def test_qa_workflow_name(self):
        """QA workflow 名字节级为 'QA'（VAL-GATE-101 家族，与 memory-core 对齐）"""
        assert re.search(r"^name:\s*QA\s*$", _read(".github/workflows/qa.yml"), re.MULTILINE)

    def test_governance_workflow_name(self):
        assert re.search(
            r"^name:\s*Evolution Governance\s*$",
            _read(".github/workflows/evolution-governance.yml"),
            re.MULTILINE,
        )


class TestReusableNoTopLevelConcurrency:
    """INFRA-626：全部 workflow_call reusable 禁止顶层 concurrency。

    caller 顶层 concurrency.group 与被调 reusable 内组名同名（或跨仓组合撞名）
    时，GitHub run 级自死锁检测直接取消 run、零 job——2026-08-29 memory #1071
    切换首 tick 实测（'Canceling since a deadlock was detected for concurrency
    group: evolution-scan between a top level workflow and scan'）。
    串行化/去重一律归 caller 顶层 concurrency（消费仓模板测试锁定）。

    覆盖全部 workflow_call 文件（新增 reusable 自动纳入），防下一个
    droid-review-shards 式残留。
    """

    @staticmethod
    def _workflow_call_files() -> list[str]:
        workflows_dir = REPO_ROOT / ".github" / "workflows"
        files: list[str] = []
        for path in sorted(workflows_dir.glob("*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            triggers = data.get("on") or data.get(True) or {}
            if "workflow_call" in triggers:
                files.append(str(path.relative_to(REPO_ROOT)))
        return files

    def test_reusable_files_discovered(self):
        files = self._workflow_call_files()
        assert files, "workflow_call 文件发现逻辑失效（glob/YAML 解析异常）"
        # 当前全部 reusable 清单——新文件自动纳入，此处仅防发现逻辑静默失效
        assert ".github/workflows/evolution-scan.yml" in files
        assert ".github/workflows/evolution-heartbeat.yml" in files
        assert ".github/workflows/droid-review-shards.yml" in files

    def test_no_reusable_carries_top_level_concurrency(self):
        offenders = [
            f
            for f in self._workflow_call_files()
            if "concurrency" in (yaml.safe_load((REPO_ROOT / f).read_text(encoding="utf-8")) or {})
        ]
        assert not offenders, (
            f"reusable 顶层 concurrency 禁令违反（INFRA-626，与 caller 组名组合"
            f"可触发 GitHub 自死锁）：{offenders}"
        )


class TestReusableDualFormKeyContract:
    """跨仓 workflow_call 键严格校验的声明面契约（CONSUMER-GATE-DEADLOCK 修复）。

    GitHub 对 caller `with:`/`secrets:` 传键做声明面严格校验——caller 传了
    callee 未声明的键 → run 级 startup_failure（零 job）；callee required 键
    caller 未传同理。跨仓改名没有原子同步窗口（pull_request_target 恒用
    main 定义），memory #1075 双写 caller × 单侧声明 callee 即 2026-08-30
    04:00Z 起 memory 三 workflow（Droid Auto Review / Auto Merge / Watchdog）
    全量 startup_failure、#1076/#1077 死锁的根因。

    本契约钉住被消费仓引用的 5 个 reusable：每个 snake 键必须带 hyphen 变体
    （required: false），且消费点熔合 `x_snake || x['x-hyphen']`（禁止裸取），
    防再次单侧删键。两步终态：memory 统一 snake-only 后，删变体键的 PR
    必须同步收缩本契约的 DUAL_FORM_FILES。
    """

    DUAL_FORM_FILES = (
        ".github/workflows/auto-merge-pipeline.yml",
        ".github/workflows/droid-review-shards.yml",
        ".github/workflows/droid-review-watchdog-handlers.yml",
        ".github/workflows/evolution-scan.yml",
        ".github/workflows/evolution-heartbeat.yml",
    )

    @classmethod
    def _dual_form_keys(cls, path: Path) -> list[tuple[str, str]]:
        """返回 (context, snake 键) 列表：workflow_call 下声明了 hyphen 变体的 snake 键。"""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = data.get("on") or data.get(True) or {}
        call = triggers.get("workflow_call", {}) or {}
        pairs: list[tuple[str, str]] = []
        for context in ("inputs", "secrets"):
            block = call.get(context, {}) or {}
            for key in block:
                if "_" in key and key.replace("_", "-") in block:
                    pairs.append((context, key))
        return pairs

    def test_dual_form_files_have_snake_keys_with_variants(self):
        """契约面自检：5 个文件各自至少存在一个双形态键（防清单失效/漂移）。"""
        for rel in self.DUAL_FORM_FILES:
            pairs = self._dual_form_keys(REPO_ROOT / rel)
            assert pairs, f"{rel} 未发现任何双形态键对——清单或声明面漂移"

    @pytest.mark.parametrize("rel", DUAL_FORM_FILES)
    def test_variants_declared_optional(self, rel: str):
        """hyphen 变体必须 required: false（required snake 会挡死未迁移 caller）。"""
        data = yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))
        triggers = data.get("on") or data.get(True) or {}
        call = triggers.get("workflow_call", {}) or {}
        offenders = []
        for context, snake in self._dual_form_keys(REPO_ROOT / rel):
            hyphen = snake.replace("_", "-")
            variant = (call.get(context, {}) or {}).get(hyphen, {})
            if variant.get("required") is not False:
                offenders.append(f"{context}:{hyphen}")
        assert not offenders, f"{rel} hyphen 变体必须可选（required: false）：{offenders}"

    @pytest.mark.parametrize("rel", DUAL_FORM_FILES)
    def test_no_bare_consumption_of_dual_form_keys(self, rel: str):
        """双形态键的消费点必须熔合，禁止裸取（防新增消费点漏熔合回退单侧语义）。"""
        raw = (REPO_ROOT / rel).read_text(encoding="utf-8")
        offenders = []
        for context, snake in self._dual_form_keys(REPO_ROOT / rel):
            bare = "${{ %s.%s }}" % (context, snake)
            if bare in raw:
                offenders.append(bare)
        assert not offenders, (
            f"{rel} 双形态键存在裸取消费点（必须熔合 x_snake || x['x-hyphen']）：{offenders}"
        )


class TestGovernanceJobNameContract:
    def test_governance_job_display_name(self):
        content = _read(".github/workflows/evolution-governance.yml")
        assert f"name: {CONTRACT_GOVERNANCE_JOB_NAME}" in content


class TestCiOkJobKeyContract:
    def test_ci_ok_job_key(self):
        content = _read(".github/workflows/ci.yml")
        assert re.search(r"^  ci-ok:\s*$", content, re.MULTILINE)


class TestGovernanceActionDefaults:
    def test_composite_action_defaults(self):
        content = _read("actions/governance-check/action.yml")
        assert "default: 'hdot123'" in content
        # 默认受保护模式覆盖 infra-core 自身 governance 路径
        for fragment in (
            ".evolution/**",
            ".github/workflows/**",
            "src/infra_core/engine/**",
            "webhook-scripts/**",
        ):
            assert fragment in content

    def test_governance_workflow_uses_shipped_action(self):
        """governance workflow 必须执行 shipped action（VAL-SCAF-006 路径感知判定），
        不能回退为只查作者不查路径的内联脚本。

        INFRA-678：action 引用 pin 到不可变 tag（v0.7.2），防 CI 漂移；
        升级 = 显式 bump 该常量。
        F3 SHA 锁定：引用改为 40 位 SHA 格式。
        """
        content = _read(".github/workflows/evolution-governance.yml")
        # F3: SHA-locked format - check for SHA-pinned governance-check reference
        assert re.search(r"hdot123-org/infra-core/actions/governance-check@[0-9a-f]{40}", content)
        # 不得回退浮动 @main 引用（CI 漂移风险）
        assert "hdot123-org/infra-core/actions/governance-check@main" not in content
        # 不得残留旧的内联作者检查（只对比作者、无路径感知）
        assert 'PR_AUTHOR="${{ github.event.pull_request.user.login }}"' not in content

    def test_governance_workflow_uses_pull_request_target(self):
        """pull_request_target 从 base 运行（受保护门禁不能被 PR 自身改写）"""
        content = _read(".github/workflows/evolution-governance.yml")
        assert "pull_request_target" in content


class TestGovernanceActionScriptPath:
    """action.yml run 行引用的脚本必须在 action 目录内且真实存在。

    修复 M1 scrutiny 发现的 blocking 缺陷：原路径 `../governance_check/governance_check.py`
    双重错误——越出 action 根 + 下划线目录名不匹配（实际是 governance-check）。
    首次真实调用即 crash-deny，M4 全部门禁切换 PR 都会触发。
    """

    def test_action_yml_references_script_within_action_dir(self):
        """action.yml 的 run 块不得包含 `..` 越出 action 根目录"""
        content = _read("actions/governance-check/action.yml")
        # 提取 run: 块（YAML 多行字符串）
        run_match = re.search(r"run:\s*\|(.+?)(?=\n\w|\Z)", content, re.DOTALL)
        assert run_match, "action.yml 必须包含 run 块"
        run_block = run_match.group(1)
        # 不得包含路径穿越（M1 scrutiny R2：原 `A or B` 断言为恒真同义反复——
        # ".." 不在蕴含 "../" 不在；收敛为真实的穿越契约 "../"）
        assert "../" not in run_block, f"action.yml run 块包含路径穿越（../）：{run_block}"

    def test_action_yml_script_path_resolves_to_existing_file(self):
        """action.yml 引用的脚本路径必须在 repo 树中真实存在"""
        content = _read("actions/governance-check/action.yml")
        # 查找 $GITHUB_ACTION_PATH/<script> 模式
        script_match = re.search(r"\$GITHUB_ACTION_PATH/(\S+\.py)", content)
        assert script_match, "action.yml 必须引用 $GITHUB_ACTION_PATH/<script>.py"
        script_name = script_match.group(1)
        # 验证脚本文件存在
        script_path = REPO_ROOT / "actions" / "governance-check" / script_name
        assert script_path.exists(), (
            f"action.yml 引用的脚本不存在：{script_path.relative_to(REPO_ROOT)}"
        )

    def test_action_yml_uses_correct_script_name(self):
        """action.yml 必须引用 governance_check.py（与目录同名但下划线）"""
        content = _read("actions/governance-check/action.yml")
        assert "$GITHUB_ACTION_PATH/governance_check.py" in content, (
            "action.yml 必须引用 $GITHUB_ACTION_PATH/governance_check.py"
        )


class TestGovernanceModuleDefaults:
    def test_module_defaults_match_composite_action(self):
        from infra_core.governance import DEFAULT_OWNER_LOGIN, DEFAULT_PROTECTED_PATTERNS

        assert DEFAULT_OWNER_LOGIN == "hdot123"
        assert DEFAULT_PROTECTED_PATTERNS == (
            ".evolution/**",
            ".github/workflows/**",
            "src/infra_core/engine/**",
            "webhook-scripts/**",
        )


class TestSetupLabelsReusableWorkflow:
    """setup-labels reusable workflow 契约测试

    验证 infra-core 提供的 setup-labels reusable workflow 满足契约：
    - workflow_call 触发器
    - labels_json input
    - created_count/skipped_count outputs
    """

    def test_setup_labels_workflow_exists(self):
        """setup-labels.yml 存在"""
        workflow_path = REPO_ROOT / ".github/workflows/setup-labels.yml"
        assert workflow_path.exists()

    def test_setup_labels_has_workflow_call_trigger(self):
        """setup-labels.yml 必须声明 workflow_call 触发器"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/setup-labels.yml"
        data = yaml.safe_load(workflow_path.read_text())
        triggers = data.get(True, {})  # YAML parses 'on:' as True key
        assert "workflow_call" in triggers, "setup-labels must declare workflow_call trigger"

    def test_setup_labels_has_labels_json_input(self):
        """setup-labels.yml 必须声明 labels_json input"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/setup-labels.yml"
        data = yaml.safe_load(workflow_path.read_text())
        triggers = data.get(True, {})
        workflow_call = triggers.get("workflow_call", {})
        inputs = workflow_call.get("inputs", {})
        assert "labels_json" in inputs, "setup-labels must declare labels_json input"
        assert inputs["labels_json"].get("type") == "string"

    def test_setup_labels_has_outputs(self):
        """setup-labels.yml 必须声明 created_count/skipped_count outputs"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/setup-labels.yml"
        data = yaml.safe_load(workflow_path.read_text())
        triggers = data.get(True, {})
        workflow_call = triggers.get("workflow_call", {})
        outputs = workflow_call.get("outputs", {})
        assert "created_count" in outputs, "setup-labels must declare created_count output"
        assert "skipped_count" in outputs, "setup-labels must declare skipped_count output"


class TestGovernanceCompositeActionMemoryCore:
    """governance composite action 对 memory-core 保护模式的支持

    memory-core 的五类保护路径：
    - .evolution/**
    - scripts/evolution_*.py
    - scripts/ (整个目录，防模块投毒)
    - .github/workflows/evolution-*.yml
    - .github/CODEOWNERS
    """

    def test_governance_check_supports_evolution_scripts_pattern(self):
        """governance_check.py 支持 scripts/evolution_*.py 模式"""
        import subprocess
        import sys
        from pathlib import Path

        script = (
            Path(__file__).resolve().parent.parent / "actions/governance-check/governance_check.py"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--author",
                "someone-else",
                "--owner",
                "hdot123",
                "--patterns",
                "scripts/evolution_*.py",
                "--files",
                "scripts/evolution_scanner.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, "Non-owner modifying evolution scripts should be denied"

    def test_governance_check_supports_scripts_dir_protection(self):
        """governance_check.py 支持 scripts/ 整个目录保护（防模块投毒）"""
        import subprocess
        import sys
        from pathlib import Path

        script = (
            Path(__file__).resolve().parent.parent / "actions/governance-check/governance_check.py"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--author",
                "someone-else",
                "--owner",
                "hdot123",
                "--patterns",
                "scripts/**",
                "--files",
                "scripts/new_module.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, "Non-owner modifying any scripts/ file should be denied"

    def test_governance_check_supports_evolution_workflows_pattern(self):
        """governance_check.py 支持 .github/workflows/evolution-*.yml 模式"""
        import subprocess
        import sys
        from pathlib import Path

        script = (
            Path(__file__).resolve().parent.parent / "actions/governance-check/governance_check.py"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--author",
                "someone-else",
                "--owner",
                "hdot123",
                "--patterns",
                ".github/workflows/evolution-*.yml",
                "--files",
                ".github/workflows/evolution-scan.yml",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, "Non-owner modifying evolution workflows should be denied"

    def test_governance_check_supports_codeowners_pattern(self):
        """governance_check.py 支持 .github/CODEOWNERS 保护"""
        import subprocess
        import sys
        from pathlib import Path

        script = (
            Path(__file__).resolve().parent.parent / "actions/governance-check/governance_check.py"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--author",
                "someone-else",
                "--owner",
                "hdot123",
                "--patterns",
                ".github/CODEOWNERS",
                "--files",
                ".github/CODEOWNERS",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, "Non-owner modifying CODEOWNERS should be denied"

    def test_governance_module_supports_memory_core_patterns(self):
        """infra_core.governance.check_governance 支持 memory-core 保护模式"""
        from infra_core.governance import check_governance

        # Test all 5 pattern types
        patterns = [
            ".evolution/**",
            "scripts/evolution_*.py",
            "scripts/**",  # whole dir protection
            ".github/workflows/evolution-*.yml",
            ".github/CODEOWNERS",
        ]

        test_cases = [
            (".evolution/config.yml", True),
            ("scripts/evolution_scanner.py", True),
            ("scripts/new_module.py", True),  # scripts/ dir protection
            (".github/workflows/evolution-scan.yml", True),
            (".github/CODEOWNERS", True),
        ]

        for file_path, should_deny in test_cases:
            verdict = check_governance(
                changed_files=[file_path],
                pr_author="someone-else",
                owner_login="hdot123",
                protected_patterns=patterns,
            )
            if should_deny:
                assert not verdict.allowed, f"Non-owner should be denied for {file_path}"
            else:
                assert verdict.allowed, f"Non-owner should be allowed for {file_path}"


class TestBranchCleanupCompositeContextGuard:
    """复合 action 上下文守卫：vars/secrets context 在 composite action 内不可用。

    根因（2026-08-27）：actions/branch-cleanup/action.yml 使用 ${{ vars.BRANCH_AGE_* }}
    导致模板校验失败（Unrecognized named-value: vars）。vars/secrets context 仅在 workflow 层合法，
    composite action 必须通过 inputs 接收值。actionlint 无法检出此问题，仅真实执行暴露。
    本测试防止回退：解析 action.yml 断言全文无 vars./secrets. context 引用。
    """

    def test_action_yml_no_vars_context(self):
        """action.yml 不得引用 vars.* context（composite action 内不合法）"""
        content = _read("actions/branch-cleanup/action.yml")
        # 搜索 vars. 模式（排除注释行）
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # 跳过注释
            if stripped.startswith("#"):
                continue
            # 检查是否包含 vars. 引用（GitHub Actions 模板语法）
            if "${{ vars." in line:
                pytest.fail(
                    f"action.yml 第 {i} 行包含 vars.* context 引用（composite action 内不合法）：{line}"
                )

    def test_action_yml_no_secrets_context(self):
        """action.yml 不得直接引用 secrets.* context（必须通过 inputs 传入）"""
        content = _read("actions/branch-cleanup/action.yml")
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "${{ secrets." in line:
                pytest.fail(
                    f"action.yml 第 {i} 行包含 secrets.* context 引用（应通过 inputs 传入）：{line}"
                )

    def test_action_yml_has_branch_age_inputs(self):
        """action.yml 必须声明 branch-age-* inputs（接收阈值）"""
        content = _read("actions/branch-cleanup/action.yml")
        for input_name in (
            "branch-age-merged-hours",
            "branch-age-closed-hours",
            "branch-age-orphan-hours",
        ):
            assert input_name in content, f"action.yml 缺少 input: {input_name}"

    def test_action_yml_uses_inputs_for_branch_age(self):
        """action.yml env 块必须使用 inputs.* 而非 vars.*"""
        content = _read("actions/branch-cleanup/action.yml")
        # 验证 env 块使用 inputs 传入
        assert "${{ inputs.branch-age-merged-hours }}" in content
        assert "${{ inputs.branch-age-closed-hours }}" in content
        assert "${{ inputs.branch-age-orphan-hours }}" in content


class TestQAWorkflowContract:
    """QA workflow 结构契约测试（gate-infra-qa-workflow feature）

    验证 infra-core qa.yml 满足 VAL-GATE-101 家族要求：
    - workflow 名 "QA"（字节级与 memory-core 对齐）
    - 三触发器（pull_request + schedule + workflow_dispatch）
    - job 家族：cli-e2e / coverage-audit / security-tests / schema-tests /
      boundary-security / full-regression / qa-ok
    - cli-e2e 引用 scripts/cli_smoke_test.sh
    - qa-ok needs 关系正确（full-regression 不在 needs 中——nightly 红不阻塞）
    - schedule-only jobs（coverage-audit / full-regression）PR 时 skip
    """

    def test_qa_workflow_exists(self):
        """qa.yml 必须存在"""
        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        assert workflow_path.exists(), "qa.yml must exist"

    def test_qa_workflow_name_byte_exact(self):
        """workflow 名必须字节级为 'QA'（与 memory-core 对齐，VAL-GATE-101）"""
        content = _read(".github/workflows/qa.yml")
        assert re.search(r"^name:\s*QA\s*$", content, re.MULTILINE), (
            "QA workflow name must be byte-exact 'QA'"
        )

    def test_qa_triggers(self):
        """三触发器：pull_request + schedule + workflow_dispatch"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        data = yaml.safe_load(workflow_path.read_text())
        triggers = data.get(True, {})  # YAML parses 'on:' as True key
        assert "pull_request" in triggers, "qa.yml must have pull_request trigger"
        assert "schedule" in triggers, "qa.yml must have schedule trigger"
        assert "workflow_dispatch" in triggers, "qa.yml must have workflow_dispatch trigger"

    def test_qa_required_jobs_exist(self):
        """QA workflow 必须包含所有必需 job"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        data = yaml.safe_load(workflow_path.read_text())
        jobs = data.get("jobs", {})
        required_jobs = {
            "cli-e2e",
            "coverage-audit",
            "security-tests",
            "schema-tests",
            "boundary-security",
            "full-regression",
            "qa-ok",
        }
        assert required_jobs.issubset(set(jobs.keys())), (
            f"QA workflow missing required jobs: {required_jobs - set(jobs.keys())}"
        )

    def test_cli_e2e_runs_smoke_script(self):
        """cli-e2e job 必须引用 scripts/cli_smoke_test.sh"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        data = yaml.safe_load(workflow_path.read_text())
        cli_e2e = data["jobs"]["cli-e2e"]
        steps = cli_e2e.get("steps", [])
        # 检查是否有任何步骤引用 cli_smoke_test.sh
        found = False
        for step in steps:
            run_cmd = step.get("run", "")
            if "cli_smoke_test.sh" in run_cmd:
                found = True
                break
        assert found, "cli-e2e job must reference scripts/cli_smoke_test.sh"

    def test_qa_ok_needs_excludes_full_regression(self):
        """qa-ok needs 不包含 full-regression（nightly 红不阻塞 PR 合并）"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        data = yaml.safe_load(workflow_path.read_text())
        qa_ok = data["jobs"]["qa-ok"]
        needs = qa_ok.get("needs", [])
        assert "full-regression" not in needs, (
            "qa-ok must NOT include full-regression in needs "
            "(nightly job can be red without blocking PR merge)"
        )

    def test_qa_ok_needs_includes_required_jobs(self):
        """qa-ok needs 必须包含所有 PR 时运行的 job"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        data = yaml.safe_load(workflow_path.read_text())
        qa_ok = data["jobs"]["qa-ok"]
        needs = qa_ok.get("needs", [])
        required_in_needs = {
            "cli-e2e",
            "coverage-audit",
            "security-tests",
            "schema-tests",
            "boundary-security",
        }
        assert required_in_needs.issubset(set(needs)), (
            f"qa-ok needs missing required jobs: {required_in_needs - set(needs)}"
        )

    def test_schedule_only_jobs_skip_on_pr(self):
        """schedule-only jobs（coverage-audit / full-regression）PR 时必须 skip"""
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/qa.yml"
        data = yaml.safe_load(workflow_path.read_text())
        for job_name in ["coverage-audit", "full-regression"]:
            job = data["jobs"][job_name]
            if_expr = job.get("if", "")
            # 必须包含事件门（schedule 或 workflow_dispatch）
            assert "schedule" in if_expr or "workflow_dispatch" in if_expr, (
                f"{job_name} must skip on PR events (schedule/dispatch only)"
            )

    def test_qa_ok_aggregation_logic(self):
        """qa-ok 聚合逻辑必须检查所有 needs job 的结果"""
        content = _read(".github/workflows/qa.yml")
        # 检查 qa-ok job 的 run 步骤是否检查所有 needs job
        qa_ok_section = content.split("qa-ok:")[1] if "qa-ok:" in content else ""
        assert "needs.cli-e2e.result" in qa_ok_section
        assert "needs.coverage-audit.result" in qa_ok_section
        assert "needs.security-tests.result" in qa_ok_section
        assert "needs.schema-tests.result" in qa_ok_section
        assert "needs.boundary-security.result" in qa_ok_section


class TestAutoMergeTriggerContract:
    """auto-merge workflow 触发器契约测试（gate-infra-auto-merge-enable feature）

    验证 infra-core 自仓 auto-merge.yml 恢复 memory-core 同构触发面：
    - workflow 名 "Auto Merge"（字节级）
    - 四触发器：workflow_run(CI/QA/Droid Auto Review/Evolution Governance completed)
      + pull_request_target(opened/synchronize/reopened) + schedule */30 + workflow_dispatch
    - INFRA-428 concurrency 组级排队：group=auto-merge-pipeline, cancel-in-progress=false
    - triage 脚本路径必须真实存在（M2 桩引用旧 scripts/ 路径的 exit-127 回归守卫）
    - 合并动作引用本仓 actions/auto-merge（VAL-HARD-104 收编）+ DISPATCH_TOKEN
      （GITHUB_TOKEN 递归防护铁律）
    - runner 铁律：jobs 一律 [self-hosted, pve-linux]
    """

    def _load_workflow(self) -> dict:
        import yaml

        workflow_path = REPO_ROOT / ".github/workflows/auto-merge.yml"
        return yaml.safe_load(workflow_path.read_text())

    def test_auto_merge_workflow_name_byte_exact(self):
        """workflow 名字节级为 'Auto Merge'"""
        content = _read(".github/workflows/auto-merge.yml")
        assert re.search(r"^name:\s*Auto Merge\s*$", content, re.MULTILINE)

    def test_auto_merge_four_triggers(self):
        """四触发器：workflow_run + pull_request_target + schedule + workflow_dispatch"""
        data = self._load_workflow()
        triggers = data.get(True, {})  # YAML parses 'on:' as True key
        for name in ("workflow_run", "pull_request_target", "schedule", "workflow_dispatch"):
            assert name in triggers, f"auto-merge must have {name} trigger"

    def test_auto_merge_workflow_run_names_byte_exact(self):
        """workflow_run 监听名与 memory-core 字节级同构（任一改名静默杀死快速路径）"""
        data = self._load_workflow()
        wr = data[True]["workflow_run"]
        assert sorted(wr["workflows"]) == sorted(
            ["CI", "QA", "Droid Auto Review", "Evolution Governance"]
        ), f"workflow_run names drifted: {wr['workflows']}"
        assert wr["types"] == ["completed"]

    def test_auto_merge_schedule_cron_30min(self):
        """schedule 兜底扫描节奏为 */30（2026-08-29 容量收敛 */10→*/30：
        降低 pve 双机 schedule 触发量；快速路径 workflow_run 不受影响）"""
        data = self._load_workflow()
        assert data[True]["schedule"] == [{"cron": "*/30 * * * *"}]

    def test_auto_merge_pr_target_types(self):
        """pull_request_target 类型：opened/synchronize/reopened"""
        data = self._load_workflow()
        assert data[True]["pull_request_target"]["types"] == [
            "opened",
            "synchronize",
            "reopened",
        ]

    def test_auto_merge_dispatch_pr_number_optional(self):
        """workflow_dispatch 的 pr_number 输入可选（缺省扫描全部 open PR）"""
        data = self._load_workflow()
        inputs = data[True]["workflow_dispatch"]["inputs"]
        assert "pr_number" in inputs
        assert inputs["pr_number"]["required"] is False
        assert inputs["pr_number"]["type"] == "string"

    def test_auto_merge_concurrency_group_queueing(self):
        """INFRA-428：组级排队设计保持（group=auto-merge-pipeline，不取消进行中腿）"""
        data = self._load_workflow()
        concurrency = data["concurrency"]
        assert concurrency["group"] == "auto-merge-pipeline"
        assert concurrency["cancel-in-progress"] is False

    def test_auto_merge_triage_script_path_exists(self):
        """workflow 引用的 triage 脚本必须在仓库树中真实存在。

        M2 桩引用旧 scripts/auto_merge_triage.sh（引擎移植后该路径已不存在），
        首个需要 triage 的真实 PR 会 exit 127。回归守卫：引用必须是
        src/infra_core/shell/auto_merge_triage.sh 且文件存在。
        """
        content = _read(".github/workflows/auto-merge.yml")
        assert "src/infra_core/shell/auto_merge_triage.sh" in content, (
            "auto-merge.yml must reference src/infra_core/shell/auto_merge_triage.sh"
        )
        assert "scripts/auto_merge_triage.sh" not in content, (
            "auto-merge.yml must not reference the retired scripts/ path (exit 127)"
        )
        assert (REPO_ROOT / "src/infra_core/shell/auto_merge_triage.sh").exists()

    def test_auto_merge_merge_step_pins_consolidated_action_and_dispatch_token(self):
        """合并动作引用本仓 actions/auto-merge（VAL-HARD-104 收编）且用 DISPATCH_TOKEN。

        GITHUB_TOKEN 必须绑定 DISPATCH_TOKEN：GitHub 递归防护会抑制
        GITHUB_TOKEN 产生的 push 事件，导致 release-please push 触发器断链。
        shared-workflows 已退役归档（M6 harden-consolidate-shared-workflows），
        引用迁移至本仓 actions/auto-merge@v0.7.2（INFRA-678 不可变 tag pin），
        shared-workflows 零残留。
        F3 SHA 锁定：引用改为 40 位 SHA 格式。
        """
        content = _read(".github/workflows/auto-merge.yml")
        # F3: SHA-locked format - check for SHA-pinned auto-merge reference
        assert re.search(r"hdot123-org/infra-core/actions/auto-merge@[0-9a-f]{40}", content)
        # 不得回退浮动 @main 引用（CI 漂移风险）
        assert "hdot123-org/infra-core/actions/auto-merge@main" not in content
        # uses: 面零 shared-workflows（注释中的移植溯源文字不算引用）
        assert not re.search(r"uses:.*shared-workflows", content), (
            "merge 步不得引用已退役的 shared-workflows（本仓 actions/auto-merge）"
        )
        assert "${{ secrets.DISPATCH_TOKEN }}" in content

    def test_auto_merge_jobs_run_on_self_hosted(self):
        """runner 铁律（2026-08-26）：jobs 一律 [self-hosted, pve-linux]"""
        data = self._load_workflow()
        for job_name, job in data["jobs"].items():
            runs_on = job.get("runs-on", [])
            assert "self-hosted" in runs_on and "pve-linux" in runs_on, (
                f"job {job_name} must run on [self-hosted, pve-linux], got {runs_on}"
            )


class TestMemoryCoreCallerParityContract:
    """VAL-GATE-111/CROSS-011（gate-contract-tests）：shipped 模板 ⇄ memory-core
    thin caller 命名契约三方对等。

    memory-core 侧 TestM4NamingContractNet 锁定消费仓 live caller 的 name ⇄ path
    全表；本类把同一契约网收敛到引擎仓 shipped 资产面：

    - **自仓镜像 workflow**（与消费仓 caller 同名注册）的 name ⇄ path 全表——
      其中 setup-labels / branch-cleanup / watchdog 等此前散落或未锁定；
    - **reusable 体的内部名**（Evolution Scan Reusable 等）——不得抢占 caller
      公开名（'Evolution Scan' / 'Evolution Heartbeat' 归消费仓 thin caller
      文件；同仓同名双注册会让 workflow_run 名单与 workflow 面板歧义）；
    - **分片模板 → caller 本地聚合契约链**：聚合 job key `droid-review` 绝不进
      reusable（check 名嵌套陷阱）+ artifact 前缀 `droid-review-debug-` +
      承载聚合的 composite action 随引擎仓发布且元数据记载该契约。

    任何一处漂移 = memory-core live callers ↔ shipped 模板 ↔ architecture §3
    三方对等破裂（VAL-CROSS-011）。
    """

    # 自仓镜像 workflow（与消费仓 caller 同名注册）
    MIRROR_WORKFLOW_NAMES = {
        "ci.yml": "CI",
        "qa.yml": "QA",
        "droid-review.yml": "Droid Auto Review",
        "evolution-governance.yml": "Evolution Governance",
        "auto-merge.yml": "Auto Merge",
        "branch-cleanup.yml": "Branch Cleanup",
        "droid-review-watchdog.yml": "Droid Review Watchdog",
        "setup-labels.yml": "Setup Labels",
        "release-please.yml": "Release Please",
    }

    # reusable 体内部名（文件被消费仓 gh run list --workflow 按文件名解析，
    # 公开名归 caller；内部名一旦漂移同样破坏本表三方对等）
    REUSABLE_BODY_NAMES = {
        "evolution-scan.yml": "Evolution Scan Reusable",
        "evolution-heartbeat.yml": "Evolution Heartbeat Reusable",
        "droid-review-shards.yml": "Droid Review Shards",
        "droid-review-watchdog-handlers.yml": "Droid Review Watchdog Handlers",
        "auto-merge-pipeline.yml": "Auto Merge Pipeline",
    }

    @pytest.mark.parametrize(
        ("filename", "expected_name"),
        sorted({**MIRROR_WORKFLOW_NAMES, **REUSABLE_BODY_NAMES}.items()),
    )
    def test_workflow_name_byte_exact(self, filename: str, expected_name: str):
        assert re.search(
            rf"^name:\s*{re.escape(expected_name)}\s*$",
            _read(f".github/workflows/{filename}"),
            re.MULTILINE,
        ), f"{filename} workflow 名漂移（三方对等契约网单点改名）: 期望 {expected_name!r}"

    def test_aggregate_composite_action_carries_local_job_key_contract(self):
        """VAL-GATE-103/111 模板侧：聚合 check 名 `droid-review` 的承载件
        （composite action）必须随引擎仓发布，且元数据记载 caller 本地 job
        契约——消费仓误把它改成 reusable workflow 调用会嵌套 check 名。"""
        action_path = REPO_ROOT / "actions/droid-review-aggregate/action.yml"
        assert action_path.exists(), (
            "droid-review-aggregate composite 必须随引擎仓发布（caller 本地聚合承载件）"
        )
        text = action_path.read_text(encoding="utf-8")
        # composite action 的 name 元数据（VAL-GATE-111: composite action name: metadata）
        assert re.search(r"^name:\s*'Droid Review Aggregate'\s*$", text, re.MULTILINE), (
            "composite action name 元数据漂移"
        )
        # 元数据必须记载 caller 本地 job key 契约与嵌套陷阱（防误改 reusable 调用的文档面）
        assert "`droid-review`" in text, (
            "composite 元数据必须记载 caller 本地 job key `droid-review` 契约"
        )
        assert "嵌套" in text, "composite 元数据必须记载 reusable 调用导致 check 名嵌套的陷阱"


class TestDroidReviewTriggerContract:
    """R1(1) 契约补钉：droid-review 恢复/切换后的 trigger 面（具体 types）。

    m4 scrutiny R1 发现：自仓 droid-review.yml 的 pull_request_target 四类
    types 与 workflow_dispatch 输入面此前无任何测试钉住（memory 侧 thin
    caller 已有 VAL-GATE-113 断言，本仓自仓文件缺失）。
    """

    def _load(self):
        return yaml.safe_load(
            (REPO_ROOT / ".github/workflows/droid-review.yml").read_text(encoding="utf-8")
        )

    def test_workflow_name_byte_exact(self):
        assert self._load()["name"] == "Droid Auto Review"

    def test_pull_request_target_types_exact(self):
        """四类事件 types 字节级（open PR 即 review 的入口面）。"""
        triggers = self._load().get("on") or self._load().get(True) or {}
        prt = triggers["pull_request_target"]
        assert prt["types"] == ["opened", "ready_for_review", "reopened", "synchronize"]
        assert "branches" not in prt and "branches-ignore" not in prt

    def test_workflow_dispatch_inputs(self):
        """dispatch 面字节级钉住（自仓形态：两输入皆可选 string——手动补跑
        入口；memory 侧 thin caller 的必填 number 形态由其自身测试钉住）。"""
        triggers = self._load().get("on") or self._load().get(True) or {}
        inputs = triggers["workflow_dispatch"]["inputs"]
        assert inputs["pr_number"]["required"] is False
        assert inputs["pr_number"]["type"] == "string"
        assert inputs["head_sha"]["required"] is False
        assert inputs["head_sha"]["type"] == "string"


class TestRepoVariablesExistence:
    """R1(2) 契约补钉：workflow 引用的 vars.X 必须在 GitHub 仓 variables 真实存在。

    此前契约测试只 pin 文件内文本引用，变量缺失（如 INFRA-606 改名后未建）
    会穿过全部契约测试。本测试优雅降级：gh 不可用 / API 不可达（CI 无凭证、
    离线）时 skip，不误报。只校验**无 `||` 兜底**的引用——带兜底的引用按
    设计允许变量缺席（脚本内回退默认值）。
    """

    REPO = "hdot123-org/infra-core"

    @classmethod
    def _required_vars(cls) -> set[str]:
        pattern = re.compile(r"vars\.([A-Z0-9_]+)(\s*\|\|)?")
        required: set[str] = set()
        for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
            lines = [
                ln
                for ln in wf.read_text(encoding="utf-8").splitlines()
                if not ln.lstrip().startswith("#") and not ln.lstrip().startswith("description:")
            ]
            for m in pattern.finditer("\n".join(lines)):
                if not m.group(2):
                    required.add(m.group(1))
        return required

    def test_required_vars_exist_on_github(self):
        required = self._required_vars()
        assert required, "工作流应至少引用一个无兜底 vars.*"
        if shutil.which("gh") is None:
            pytest.skip("gh CLI 不可用（优雅降级）")
        probe = subprocess.run(
            ["gh", "api", f"repos/{self.REPO}/actions/variables", "--jq", ".variables[].name"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode != 0:
            pytest.skip(f"gh API 不可达（无凭证/离线）: {probe.stderr.strip()[:80]}")
        existing = {ln.strip() for ln in probe.stdout.splitlines() if ln.strip()}
        missing = required - existing
        assert not missing, (
            f"workflow 引用的无兜底 vars 在 GitHub 仓缺失: {sorted(missing)}"
            f"（已有: {sorted(existing)}）"
        )
