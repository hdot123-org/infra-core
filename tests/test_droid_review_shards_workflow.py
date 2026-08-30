"""droid-review-shards reusable workflow 契约测试（M4 gate-droid-review）

锁定 memory-core thin caller 所依赖的 reusable workflow 不变量：
- workflow_call 触发面：inputs / secrets / outputs
- 分片流水线 3-job 结构（setup / plan-shards / review-shard matrix）
- artifact 前缀 droid-review-debug-（watchdog quota-sweep 契约）
- 引擎脚本自 infra-core checkout（不依赖消费仓 scripts/droid_review 副本）
- 反嵌套设计：本文件绝不定义聚合 job（check 名 `droid-review` 精确契约
  由 caller 本地 job + composite action 承载，见 VAL-GATE-103）

与 tests/test_droid_review_byom_tailnet.py 的分工：该文件锁 BYOM 路由，
本文件锁结构与契约。
"""

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.schema, pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/droid-review-shards.yml"
ENGINE_PLAN = "engine/src/infra_core/engine/droid_review/plan_shards.py"
ENGINE_RUN_SHARD = "engine/src/infra_core/engine/droid_review/run_shard.sh"


@pytest.fixture(scope="module")
def shards_data() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text())


@pytest.fixture(scope="module")
def workflow_call(shards_data) -> dict:
    triggers = shards_data.get(True, {}) or shards_data.get("on", {})
    assert "workflow_call" in triggers, "droid-review-shards 必须声明 workflow_call 触发器"
    return triggers["workflow_call"]


class TestWorkflowCallSurface:
    """workflow_call inputs/secrets/outputs 契约（thin caller 的调用面）"""

    def test_inputs_declared(self, workflow_call):
        inputs = workflow_call.get("inputs", {})
        for name in (
            "engine_ref",
            "pr_number",
            "head_sha",
            "shard_max_files",
            "shard_max_count",
            "shard_timeout_minutes",
            "shard_max_parallel",
            # hyphen 过渡变体（双形态并存，CONSUMER-GATE-DEADLOCK 修复）
            "engine-ref",
            "pr-number",
            "head-sha",
            "shard-max-files",
            "shard-max-count",
            "shard-timeout-minutes",
            "shard-max-parallel",
        ):
            assert name in inputs, f"workflow_call 缺少 input: {name}"

    def test_input_defaults_match_budget_layers(self, workflow_call):
        """预算层默认值与 VAL-SHARD-011 一致（caller 未转发时兜底）"""
        inputs = workflow_call.get("inputs", {})
        assert inputs["shard_max_files"]["default"] == "25"
        assert inputs["shard_max_count"]["default"] == "6"
        assert inputs["shard_timeout_minutes"]["default"] == "45"
        assert inputs["shard_max_parallel"]["default"] == "3"
        assert inputs["engine_ref"]["default"] == "main"

    def test_secrets_declared(self, workflow_call):
        secrets = workflow_call.get("secrets", {})
        assert "FACTORY_API_KEY" in secrets, "必须声明 FACTORY_API_KEY（droid exec 凭证）"
        assert secrets["FACTORY_API_KEY"].get("required") is True
        assert "NVIDIA_KONG_PROXY_KEY" in secrets, "必须声明 NVIDIA_KONG_PROXY_KEY 注入面"

    def test_outputs_exposed_for_local_aggregate(self, workflow_call):
        """caller 本地 droid-review job 依赖这些输出驱动 composite action"""
        outputs = workflow_call.get("outputs", {})
        for name in ("pr_number", "base_sha", "head_sha", "docs_only", "shards"):
            assert name in outputs, f"workflow_call 缺少 output: {name}"
        # plan_shards_ok 把 `needs.plan-shards.result == 'success'` 语义透传给 caller
        # （末步置位实现：job skipped/failure 时输出为空，actionlint 对
        # workflow 输出中的 jobs.<id>.result 引用会拒绝，故用输出透传）
        assert "plan_shards_ok" in outputs
        assert "plan-shards.outputs.plan_ok" in outputs["plan_shards_ok"]["value"]


class TestDualFormInputs:
    """双形态键声明 + 取值熔合（CONSUMER-GATE-DEADLOCK 修复，2026-08-30）。

    GitHub 对 caller with: 传键做声明面严格校验：caller 传了 callee 未声明键
    → run 级 startup_failure（零 job）。memory #1075 双写 caller（snake +
    hyphen 并传）× 单侧声明 callee 即 04:08Z Droid Auto Review 断链根因。
    每个snake 键必须带 hyphen 变体（required: false），消费点统一熔合
    `inputs.x_snake || inputs['x-hyphen']`。两步终态：memory 统一 snake-only
    后本契约随删变体键的 PR 一并退役。
    """

    DUAL_FORM_SNAKE_KEYS = (
        "engine_ref",
        "pr_number",
        "head_sha",
        "shard_max_files",
        "shard_max_count",
        "shard_timeout_minutes",
        "shard_max_parallel",
    )

    def test_hyphen_variants_declared_optional(self, workflow_call):
        inputs = workflow_call.get("inputs", {})
        for snake in self.DUAL_FORM_SNAKE_KEYS:
            hyphen = snake.replace("_", "-")
            assert hyphen in inputs, f"缺少 hyphen 变体 input: {hyphen}"
            assert inputs[hyphen]["required"] is False, f"{hyphen} 变体必须可选"
            assert inputs[hyphen]["type"] == "string"

    def test_fusion_expressions_at_every_consumption(self, shards_data):
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        expected_fusions = (
            "ref: ${{ inputs.engine_ref || inputs['engine-ref'] }}",
            "PR_NUMBER=\"${{ inputs.pr_number || inputs['pr-number'] }}\"",
            "HEAD_SHA=\"${{ inputs.head_sha || inputs['head-sha'] }}\"",
            "MAX_FILES: ${{ inputs.shard_max_files || inputs['shard-max-files'] }}",
            "MAX_COUNT: ${{ inputs.shard_max_count || inputs['shard-max-count'] }}",
            (
                "timeout-minutes: ${{ fromJSON(inputs.shard_timeout_minutes"
                " || inputs['shard-timeout-minutes']) }}"
            ),
            (
                "max-parallel: ${{ fromJSON(inputs.shard_max_parallel"
                " || inputs['shard-max-parallel']) }}"
            ),
        )
        for fusion in expected_fusions:
            assert fusion in raw, f"缺少取值熔合表达式: {fusion}"

    def test_no_bare_snake_input_consumption(self, shards_data):
        """声明了 hyphen 变体的 snake 键禁止裸取（防未来新增消费点漏熔合）。"""
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        for snake in self.DUAL_FORM_SNAKE_KEYS:
            bare = "${{ inputs.%s }}" % snake
            assert bare not in raw, (
                f"inputs.{snake} 存在裸取消费点——必须熔合 inputs.{snake} "
                f"|| inputs['{snake.replace('_', '-')}']"
            )


class TestShardPipelineStructure:
    """3-job 分片流水线结构（setup / plan-shards / review-shard matrix）"""

    def test_three_job_architecture(self, shards_data):
        jobs = shards_data["jobs"]
        assert "setup" in jobs
        assert "plan-shards" in jobs
        assert "review-shard" in jobs

    def test_no_aggregate_job_anti_nesting(self, shards_data):
        """反嵌套设计：reusable workflow 绝不定义项名为 droid-review 的 job。

        reusable 内部 job 的 check 名是 `外层/内层` 嵌套格式，若聚合 job 进
        本文件，check 名变为 `shards / droid-review` 之类，精确名匹配
        （check_droid_review.sh / ci-ok / branch protection）全部失效。
        """
        assert "droid-review" not in shards_data["jobs"], (
            "聚合 job 绝不能进 reusable workflow（check 名嵌套陷阱，VAL-GATE-103）"
        )

    def test_review_shard_uses_matrix(self, shards_data):
        """VAL-GATE-002 等价：review-shard matrix 分片并行"""
        job = shards_data["jobs"]["review-shard"]
        assert "strategy" in job
        assert "matrix" in job["strategy"]
        assert "shard" in job["strategy"]["matrix"]

    def test_review_shard_fail_fast_false(self, shards_data):
        job = shards_data["jobs"]["review-shard"]
        assert job["strategy"]["fail-fast"] is False

    def test_review_shard_gated_on_docs_only(self, shards_data):
        """VAL-DRSKIP-004 等价：review-shard job 级 if 排除 docs-only PR"""
        job_if = str(shards_data["jobs"]["review-shard"].get("if", ""))
        assert "docs_only" in job_if

    def test_all_jobs_self_hosted_runner(self, shards_data):
        """Runner 铁律：分片流水线一律 [self-hosted, pve-linux]"""
        for job_id, job in shards_data["jobs"].items():
            assert job.get("runs-on") == ["self-hosted", "pve-linux"], (
                f"job {job_id} runs-on 漂移：{job.get('runs-on')}"
            )

    def test_no_setup_venv_reference(self, shards_data):
        """reusable workflow 不得引用 ./.github/actions/setup-venv（消费仓没有该
        composite，引用即 caller 侧解析失败）。分片流水线仅依赖
        python3 stdlib + jq + gh + droid CLI。"""
        assert "setup-venv" not in WORKFLOW_PATH.read_text()


class TestEngineSelfContainment:
    """引擎脚本来自 infra-core checkout，不依赖消费仓 scripts/droid_review 副本"""

    def test_plan_shards_uses_engine_path(self, shards_data):
        plan_job = shards_data["jobs"]["plan-shards"]
        plan_step = next((s for s in plan_job["steps"] if s.get("id") == "plan"), None)
        assert plan_step is not None
        assert ENGINE_PLAN in plan_step["run"], "plan-shards 必须执行引擎副本 plan_shards.py"

    def test_review_shard_uses_engine_run_shard(self, shards_data):
        review_job = shards_data["jobs"]["review-shard"]
        run_step = next(
            (s for s in review_job["steps"] if s.get("name") == "Run shard review"), None
        )
        assert run_step is not None
        assert ENGINE_RUN_SHARD in run_step["run"], "review-shard 必须执行引擎副本 run_shard.sh"

    def test_engine_checkouts_declared(self, shards_data):
        """plan-shards 与 review-shard 都 checkout infra-core 引擎"""
        for job_id in ("plan-shards", "review-shard"):
            job = shards_data["jobs"][job_id]
            engine_steps = [
                s
                for s in job["steps"]
                if s.get("uses", "").startswith("actions/checkout")
                and s.get("with", {}).get("repository") == "hdot123-org/infra-core"
            ]
            assert engine_steps, f"job {job_id} 缺少 infra-core 引擎 checkout"
            assert engine_steps[0]["with"].get("ref") == (
                "${{ inputs.engine_ref || inputs['engine-ref'] }}"
            )

    def test_review_shard_dual_checkout_of_consumer_repo(self, shards_data):
        """安全模型保持：BASE checkout（脚本/prompt）+ HEAD checkout（head-src/）
        （VAL-SHARD-006，自 memory-core test_07 迁入）"""
        review_job = shards_data["jobs"]["review-shard"]
        head_checkout = [
            s
            for s in review_job["steps"]
            if s.get("uses", "").startswith("actions/checkout")
            and s.get("with", {}).get("path") == "head-src"
        ]
        assert head_checkout, "review-shard 必须保留 HEAD checkout（head-src/）"

    def test_shard_env_reads_setup_outputs(self, shards_data):
        """VAL-SHARD（自 memory-core test_10c 迁入）：shard_env 必须从
        needs.setup.outputs 读 sha（workflow_dispatch 触发时
        github.event.pull_request.*.sha 为空，读 event 会让 shard 永远进不了流水线）。"""
        review_job = shards_data["jobs"]["review-shard"]
        shard_env = next((s for s in review_job["steps"] if s.get("id") == "shard_env"), None)
        assert shard_env is not None, "review-shard must have a shard_env step"
        env = shard_env.get("env", {})
        assert "needs.setup.outputs" in str(env.get("BASE_SHA", ""))
        assert "needs.setup.outputs" in str(env.get("HEAD_SHA", ""))
        assert "github.event.pull_request" not in str(env.get("BASE_SHA", ""))
        assert "github.event.pull_request" not in str(env.get("HEAD_SHA", ""))

    def test_no_depth_1_in_base_fetch(self, shards_data):
        """VAL-SHARD-002（自 memory-core test_10d 迁入）：base SHA fetch 禁止
        --depth=1（shallow graft 阻断 merge-base 历史遍历，base 前进过的 PR 全部 fail-close）。"""
        review_job = shards_data["jobs"]["review-shard"]
        shard_env = next((s for s in review_job["steps"] if s.get("id") == "shard_env"), None)
        run_block = shard_env["run"]
        assert 'git fetch origin "$BASE_SHA"' in run_block
        # 只检查实际 git fetch 命令行，忽略注释行（run_block 含「禁止 --depth=1」
        # 提示注释，全文匹配会误报命中注释文本）
        fetch_lines = [
            line
            for line in (raw.strip() for raw in run_block.splitlines())
            if line.startswith("git fetch")
        ]
        assert fetch_lines, "run_block 必须包含实际的 git fetch 命令行"
        for line in fetch_lines:
            assert "--depth=1" not in line, f"git fetch 命令行禁止 --depth=1: {line}"

    def test_artifact_includes_debug_transcripts_and_error_logs(self, shards_data):
        """VAL-SHARD-012（自 memory-core test_10e 迁入）：debug artifact 必须含
        session transcripts 与执行错误日志（watchdog quota-sweep 与失败诊断依赖）。"""
        review_job = shards_data["jobs"]["review-shard"]
        upload_step = next(
            (
                s
                for s in review_job["steps"]
                if s.get("uses", "").startswith("actions/upload-artifact")
            ),
            None,
        )
        paths = upload_step["with"]["path"]
        for fragment in (
            "findings-shard-*.json",
            "shard-*.diff",
            "shard-exec-error.log",
            "droid-exec-stdout.json",
            ".factory/sessions/**",
        ):
            assert fragment in paths, f"artifact path 缺少 {fragment}"

    def test_run_shard_schema_validation_is_self_locating(self):
        """引擎 run_shard.sh 的 validate_findings 导入从脚本自身目录解析。

        reusable workflow 在消费仓任意 CWD 运行；旧式 sys.path.insert(0, 'scripts')
        依赖消费仓 scripts/droid_review/ 布局（M5 删除后即断）。
        """
        script = (REPO_ROOT / "src/infra_core/engine/droid_review/run_shard.sh").read_text()
        assert "sys.path.insert(0, 'scripts')" not in script, (
            "run_shard.sh 不得依赖 CWD 相对 scripts/ 布局（引擎自包含要求）"
        )
        assert (
            "BASH_SOURCE" in script and "from publish_findings import validate_findings" in script
        )


class TestArtifactPrefixContract:
    """artifact 前缀 droid-review-debug-（watchdog quota-sweep startswith 消费）"""

    def test_upload_artifact_prefix_preserved(self, shards_data):
        """VAL-CROSS-032 等价（从消费仓 workflow 迁入引擎仓）"""
        review_job = shards_data["jobs"]["review-shard"]
        upload_step = next(
            (
                s
                for s in review_job["steps"]
                if s.get("uses", "").startswith("actions/upload-artifact")
            ),
            None,
        )
        assert upload_step is not None, "review-shard 缺少 findings artifact 上传"
        artifact_name = upload_step.get("with", {}).get("name", "")
        assert artifact_name.startswith("droid-review-debug-"), (
            f"artifact 前缀漂移：{artifact_name}"
        )
        assert "shard-${{ matrix.shard.shard_id }}" in artifact_name

    def test_upload_include_hidden_files(self, shards_data):
        """session transcripts 在 .factory/（隐藏目录），必须 include-hidden-files"""
        review_job = shards_data["jobs"]["review-shard"]
        upload_step = next(
            (
                s
                for s in review_job["steps"]
                if s.get("uses", "").startswith("actions/upload-artifact")
            ),
            None,
        )
        assert upload_step["with"].get("include-hidden-files") is True


class TestDocsOnlyDetection:
    """VAL-DRSKIP-001/002/003 等价（从消费仓 workflow 迁入引擎仓）"""

    @pytest.fixture
    def detect_step(self, shards_data) -> dict:
        plan_job = shards_data["jobs"]["plan-shards"]
        step = next((s for s in plan_job["steps"] if s.get("name") == "Detect docs-only PR"), None)
        assert step is not None, "Detect docs-only PR step 缺失"
        return step

    def test_detect_step_outputs_skip(self, detect_step):
        assert "skip=true" in detect_step["run"]
        assert "skip=false" in detect_step["run"]

    def test_detect_fail_closed(self, detect_step):
        assert "fail-closed" in detect_step["run"]

    def test_detect_md_suffix_rule(self, detect_step):
        assert "grep -v '\\.md$'" in detect_step["run"]


class TestWorkspaceGuardProbe:
    """reusable 版 workspace guard 探针用 pyproject.toml（消费仓无关 setup-venv）"""

    def test_probe_is_pyproject_toml(self, shards_data):
        raw = WORKFLOW_PATH.read_text()
        assert raw.count("pyproject.toml") >= 2, "workspace guard 探针应为 pyproject.toml"
        assert ".github/actions/setup-venv" not in raw


class TestNoTopLevelConcurrency:
    """reusable 顶层 concurrency 禁令（INFRA-626）。

    历史注：本文件曾按 head SHA 分组做同 head 去重（PR #61 实测同 head
    3 条并行 run 浪费 pve 池），2026-08-29 随 INFRA-626 移除——reusable 顶层
    concurrency 与 caller 顶层组名组合可触发 GitHub run 级自死锁（evolution
    系 #1071 首 tick 实测零 job 秒取消）。同 head 去重若需要，归 caller 顶层
    concurrency 表达（消费仓模板测试锁定）。
    """

    def test_reusable_must_not_carry_top_level_concurrency(self, shards_data):
        assert "concurrency" not in shards_data, (
            "droid-review-shards reusable 不得携带顶层 concurrency"
            "（与 caller 组名组合可触发 GitHub 自死锁，INFRA-626）"
        )
