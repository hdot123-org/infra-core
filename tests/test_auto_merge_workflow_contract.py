"""auto-merge workflow 防毒契约测试（sparse-checkout 工作区污染回归锁定）

背景（2026-08-28 三 runner 污染事故，#48 回归）：auto-merge job 曾以
actions/checkout + sparse-checkout（cone-mode false）只取 triage 单文件。
GitHub-hosted runner 上工作区每 run 重建、无害；但 self-hosted 共享持久
工作区上，checkout 会把该工作区 .git/config 写成 core.sparseCheckout=true
并把工作树裁剪到极小集合——同一 runner 后续所有复用该工作区的 CI job 以
"Can't find action.yml under .github/actions/setup-venv" 失败，且每次
auto-merge 触发都重新污染（排毒三次后仍复发实证）。

本文件锁定六条不变量：
1. auto-merge.yml 任何 job 都不得使用 actions/checkout（该 job 零工作区足迹；
   防毒上优于"去 sparse-checkout 保留全量 checkout"）；
2. 解析后的 workflow 结构中不存在 sparse-checkout / sparse-checkout-cone-mode
   输入（注释中的禁令引用不出现在解析结构里，不影响本断言）；
3. 内联 triage 脚本与 src/infra_core/shell/auto_merge_triage.sh 逐字节一致
   （heredoc 副本禁止静默漂移——workflow 内联版是行为的唯一运行时来源，
   源文件是唯一编辑来源，两者必须同步演进）；
4. triage 调用指向 RUNNER_TEMP（每 run 独立、run 结束即清理），不引用
   工作区相对路径；
5. 门禁 workflow（ci/qa/droid-review）每个 actions/checkout 之前必须有
   Workspace guard 运行时排毒步骤（checkout 自带的 sparse-checkout disable
   实证无法恢复被裁剪的工作树，残留 .git 必须删除重建）；
6. auto-merge job 首步即 Workspace guard——该 job 每 sweep 在三 runner 上
   轮转，是残留毒区的常驻自愈向量。
"""

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTO_MERGE_YML = REPO_ROOT / ".github/workflows/auto-merge.yml"
# M4 gate-watchdog-automerge：reusable 版 resolve+triage+merge 流水线（memory-core
# thin caller 载体）。防毒/字节一致不变量与自仓 caller 完全同构，逐条锁定。
AUTO_MERGE_PIPELINE_YML = REPO_ROOT / ".github/workflows/auto-merge-pipeline.yml"
AUTO_MERGE_CARRIERS = (AUTO_MERGE_YML, AUTO_MERGE_PIPELINE_YML)
SHARED_WORKFLOWS_PIN = (
    "hdot123-org/shared-workflows/auto-merge@5a0fc1b8946a170a12687d8614d56189e1f8dab5"
)
TRIAGE_SH = REPO_ROOT / "src/infra_core/shell/auto_merge_triage.sh"
GUARDED_CHECKOUT_WORKFLOWS = ("ci.yml", "qa.yml", "droid-review.yml")
GUARD_MARKER = 'rm -rf "$GITHUB_WORKSPACE/.git"'

SPARSE_CHECKOUT_KEYS = frozenset({"sparse-checkout", "sparse-checkout-cone-mode"})


def _load_doc(path: Path = AUTO_MERGE_YML) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name} 必须是 YAML mapping"
    return doc


def _iter_keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _iter_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_keys(item)


def _steps(doc: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for job_name, job in (doc.get("jobs") or {}).items():
        assert isinstance(job, dict), f"job {job_name} 必须是 mapping"
        for step in job.get("steps") or []:
            assert isinstance(step, dict), f"job {job_name} 存在非 mapping 步骤"
            yield str(job_name), step


def _triage_run_script(doc: dict[str, Any]) -> str:
    triage_steps = [
        step
        for _, step in _steps(doc)
        if step.get("id") == "triage" and isinstance(step.get("run"), str)
    ]
    assert len(triage_steps) == 1, "必须恰好包含一个 id=triage 的 run 步骤"
    return triage_steps[0]["run"]


class TestNoWorkspaceFootprint:
    @pytest.mark.parametrize("carrier", AUTO_MERGE_CARRIERS)
    def test_no_job_uses_actions_checkout(self, carrier: Path) -> None:
        """防毒铁律：auto-merge 两载体（自仓 caller + reusable pipeline）全部 job
        禁止 actions/checkout。

        checkout 是唯一会把 core.sparseCheckout=true 写进共享工作区
        .git/config 的入口；该 job 所需的 triage 脚本经 heredoc 内联，
        无需仓库工作区， checkout 必须整步移除而非仅去 sparse 参数。
        """
        offenders = [
            f"{job_name}: {step['uses']}"
            for job_name, step in _steps(_load_doc(carrier))
            if str(step.get("uses", "")).startswith("actions/checkout")
        ]
        assert not offenders, (
            f"{carrier.name} 禁止 actions/checkout（self-hosted 共享工作区防毒），"
            f"违规步骤: {offenders}"
        )

    @pytest.mark.parametrize("carrier", AUTO_MERGE_CARRIERS)
    def test_no_sparse_checkout_inputs_in_structure(self, carrier: Path) -> None:
        """解析后的 workflow 结构不得出现任何 sparse-checkout 输入。"""
        keys = set(_iter_keys(_load_doc(carrier)))
        offenders = sorted(keys & SPARSE_CHECKOUT_KEYS)
        assert not offenders, f"{carrier.name} 结构含 sparse-checkout 输入: {offenders}"


class TestInlineTriageParity:
    @pytest.mark.parametrize("carrier", AUTO_MERGE_CARRIERS)
    def test_triage_heredoc_byte_identical_to_source(self, carrier: Path) -> None:
        """heredoc 内联脚本必须与 src/ 源文件逐字节一致（防静默漂移）。

        锁定两份载体：自仓 auto-merge.yml + reusable auto-merge-pipeline.yml
        （M4 gate-watchdog-automerge 起 memory-core thin caller 走后者）。
        """
        run_script = _triage_run_script(_load_doc(carrier))
        match = re.search(r"<<'TRIAGE_EOF'\n(.*?)\nTRIAGE_EOF\n", run_script, re.DOTALL)
        assert match, f"{carrier.name} triage 步骤必须以 <<'TRIAGE_EOF' heredoc 内联脚本"
        inlined = match.group(1) + "\n"
        source = TRIAGE_SH.read_text(encoding="utf-8")
        assert inlined == source, (
            f"{carrier.name} 内联 triage 脚本与 "
            "src/infra_core/shell/auto_merge_triage.sh 漂移——三份（src + 两载体）必须同步修改"
        )

    @pytest.mark.parametrize("carrier", AUTO_MERGE_CARRIERS)
    def test_triage_invocation_targets_runner_temp(self, carrier: Path) -> None:
        """triage 调用必须指向 RUNNER_TEMP，禁止工作区相对路径残留。"""
        run_script = _triage_run_script(_load_doc(carrier))
        assert 'bash "$RUNNER_TEMP/auto_merge_triage.sh"' in run_script, (
            f"{carrier.name}: triage 必须经 $RUNNER_TEMP 调用内联脚本"
        )
        assert "bash src/infra_core/shell/auto_merge_triage.sh" not in run_script, (
            f"{carrier.name}: triage 不得经工作区相对路径执行脚本（本 job 无工作区；注释中的路径引用不受限）"
        )


def _job_steps(path: Path) -> Iterator[tuple[str, str, list[dict[str, Any]]]]:
    """遍历 (workflow 名, job 名, steps 列表)。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in (doc.get("jobs") or {}).items():
        steps = (job or {}).get("steps") or []
        yield path.name, str(job_name), steps


class TestWorkspaceGuard:
    """checkout 前置运行时排毒守卫（2026-08-28 残留毒区自愈机制）。

    actions/checkout 自带的 `git sparse-checkout disable` 实证无法恢复被
    裁剪的工作树（disable 后仍缺 .github/actions/setup-venv，CI 全线
    ~13s 失败）。守卫必须在 checkout 前以纯 shell 内联 run 检测残留并
    删除 .git——工作树残缺时本地 composite action 同样无法解析，不可
    封装为 action。
    """

    @pytest.mark.parametrize("workflow", GUARDED_CHECKOUT_WORKFLOWS)
    def test_every_checkout_preceded_by_guard(self, workflow: str) -> None:
        path = REPO_ROOT / ".github/workflows" / workflow
        for wf_name, job_name, steps in _job_steps(path):
            for idx, step in enumerate(steps):
                uses = str(step.get("uses", ""))
                if not uses.startswith("actions/checkout"):
                    continue
                assert idx > 0, f"{wf_name}/{job_name}: checkout 是首步，缺 Workspace guard"
                prev = steps[idx - 1]
                prev_run = str(prev.get("run", ""))
                assert GUARD_MARKER in prev_run and "sparse" in prev.get("name", ""), (
                    f"{wf_name}/{job_name}: checkout 前一步不是 Workspace guard"
                )

    def test_no_unaccompanied_checkout_count(self) -> None:
        """守卫数量与 checkout 数量一致（防未来新增 job 漏配守卫）。"""
        for workflow in GUARDED_CHECKOUT_WORKFLOWS:
            path = REPO_ROOT / ".github/workflows" / workflow
            checkouts = 0
            guards = 0
            for _, _, steps in _job_steps(path):
                for step in steps:
                    if str(step.get("uses", "")).startswith("actions/checkout"):
                        checkouts += 1
                    if "sparse" in str(step.get("name", "")):
                        guards += 1
            assert checkouts == guards, (
                f"{workflow}: checkout({checkouts}) 与守卫({guards})数量不一致"
            )

    @pytest.mark.parametrize("carrier", AUTO_MERGE_CARRIERS)
    def test_automerge_job_first_step_is_guard(self, carrier: Path) -> None:
        """auto-merge job 首步 = Workspace guard：每 sweep runner 池常驻自愈。"""
        steps = _load_doc(carrier)["jobs"]["auto-merge"]["steps"]
        first = steps[0]
        assert "sparse" in str(first.get("name", "")), (
            f"{carrier.name}: auto-merge job 首步必须是 Workspace guard"
        )
        assert GUARD_MARKER in str(first.get("run", "")), (
            f"{carrier.name}: guard 步骤必须包含排毒逻辑"
        )


class TestReusablePipelineTemplateContract:
    """auto-merge-pipeline.yml reusable 模板契约（M4 gate-watchdog-automerge）。

    锁定 memory-core thin caller（VAL-GATE-106）所依赖的不变量：
    触发面归 caller（workflow_run 四名单 / pull_request_target / schedule /
    workflow_dispatch + 事件门控 + concurrency 全部不进本文件）；本文件只承载
    resolve+triage+merge 执行体；shared-workflows merge pin 在 M4 冻结不动。
    """

    def test_workflow_name(self) -> None:
        assert _load_doc(AUTO_MERGE_PIPELINE_YML)["name"] == "Auto Merge Pipeline"

    def test_only_workflow_call_trigger(self) -> None:
        """触发面归 caller：本文件只允许 workflow_call，禁止自带任何触发器。"""
        pipeline_data = _load_doc(AUTO_MERGE_PIPELINE_YML)
        triggers = pipeline_data.get(True, {}) or pipeline_data.get("on", {})
        assert set(triggers.keys()) == {"workflow_call"}, (
            f"reusable 不得自带触发器（workflow_run 名单留在 caller），实际: {list(triggers.keys())}"
        )

    def test_no_event_guard_inside_reusable(self) -> None:
        """事件门控（workflow_run 仅 success 尝试合并）归 caller：本文件零守卫引用。"""
        raw = AUTO_MERGE_PIPELINE_YML.read_text(encoding="utf-8")
        assert "conclusion == 'success'" not in raw
        assert "event_name == 'workflow_run' &&" not in raw

    def test_dispatch_token_secret_input_required(self) -> None:
        pipeline_data = _load_doc(AUTO_MERGE_PIPELINE_YML)
        secrets_block = pipeline_data[True]["workflow_call"].get("secrets", {})
        assert "dispatch-token" in secrets_block, "必须声明 dispatch-token secret 输入"
        assert secrets_block["dispatch-token"]["required"] is True

    def test_job_topology(self) -> None:
        jobs = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]
        assert set(jobs.keys()) == {"resolve", "auto-merge"}
        assert jobs["auto-merge"].get("needs") == "resolve"
        matrix = jobs["auto-merge"]["strategy"]["matrix"]
        assert matrix["pr_number"] == "${{ fromJSON(needs.resolve.outputs.pr_numbers) }}"

    def test_merge_step_shared_workflows_pin_frozen(self) -> None:
        """VAL-GATE-106：merge 步引用 shared-workflows/auto-merge@5a0fc1b… 冻结不动（M6 才合并）。"""
        steps = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]["auto-merge"]["steps"]
        merge_step = next(
            (s for s in steps if "shared-workflows/auto-merge" in str(s.get("uses", ""))),
            None,
        )
        assert merge_step is not None, "shared-workflows/auto-merge merge 步缺失"
        assert merge_step["uses"] == SHARED_WORKFLOWS_PIN, (
            f"shared-workflows pin 必须字节级冻结，实际: {merge_step['uses']}"
        )

    def test_merge_step_uses_dispatch_token_not_github_token(self) -> None:
        """合并凭证必须来自 dispatch-token secret 输入（PAT 防递归抑制），绝不回退 GITHUB_TOKEN。"""
        steps = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]["auto-merge"]["steps"]
        merge_step = next(
            s for s in steps if "shared-workflows/auto-merge" in str(s.get("uses", ""))
        )
        env = merge_step.get("env", {})
        assert env.get("GITHUB_TOKEN") == "${{ secrets.dispatch-token }}", (
            f"merge 步 GITHUB_TOKEN env 必须经 dispatch-token secret 传入，实际: {env.get('GITHUB_TOKEN')}"
        )

    def test_permissions_block(self) -> None:
        perms = _load_doc(AUTO_MERGE_PIPELINE_YML).get("permissions", {})
        assert perms == {"contents": "write", "pull-requests": "write", "checks": "read"}

    def test_all_jobs_self_hosted(self) -> None:
        for job_name, job in _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"].items():
            assert job.get("runs-on") == ["self-hosted", "pve-linux"], (
                f"{job_name} 必须跑自建 runner（禁止 ubuntu-latest）"
            )

    def test_workspace_guard_probe_uses_consumer_agnostic_file(self) -> None:
        """reusable 版 guard 探针必须用 pyproject.toml（消费仓共有文件，
        不用本仓特有 .github/actions/setup-venv 路径——droid-review-shards 先例）。"""
        steps = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]["auto-merge"]["steps"]
        guard_run = str(steps[0].get("run", ""))
        assert "pyproject.toml" in guard_run
        assert ".github/actions/setup-venv" not in guard_run
