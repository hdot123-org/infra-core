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
# M6 harden-consolidate-shared-workflows（VAL-HARD-104）：shared-workflows 仓退役
# （README 重定向 + 归档），merge action 行为等价移植为本仓 actions/auto-merge。
# 引用走 owner/repo 全路径 + 不可变 tag pin（INFRA-678：@main → @v0.7.2，
# 防 CI 漂移；升级 = 显式 bump 该常量，回滚 = revert 本 PR，main 上的引用
# 一并还原，归档仓的旧 pin 仍可解析，无第二处 pin 需要同步）。
AUTO_MERGE_ACTION_REF = "hdot123-org/infra-core/actions/auto-merge@v0.7.2"
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
    resolve+triage+merge 执行体；merge 步引用本仓 actions/auto-merge
    （M6 VAL-HARD-104 自 shared-workflows@5a0fc1b 行为等价收编，该仓退役归档）。
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

    def test_dispatch_token_dual_form_declared_optional(self) -> None:
        """双形态键声明（CONSUMER-GATE-DEADLOCK 修复 2026-08-30）。

        GitHub 对 caller secrets: 传键做声明面严格校验——caller 传了未声明键
        → run 级 startup_failure（零 job）。memory #1075 双写 caller
        （dispatch_token + dispatch-token 并传）× 单侧声明 callee 即
        04:40Z auto-merge 断链根因。两形态均声明且 required: false：
        memory main auto-merge.yml 在 #1076 合并前仅传 hyphen 形态
        （INFRA-636），required snake 会把 #1076/#1077 唯一的自动合并通道
        挡死；缺凭证的 fail-closed 语义由运行时合并步凭证失败保持。
        """
        pipeline_data = _load_doc(AUTO_MERGE_PIPELINE_YML)
        secrets_block = pipeline_data[True]["workflow_call"].get("secrets", {})
        assert "dispatch_token" in secrets_block, (
            "必须声明 dispatch_token secret 输入（M5 R1(3) snake_case 统一）"
        )
        assert "dispatch-token" in secrets_block, (
            "必须声明 hyphen 过渡变体 dispatch-token（双形态并存，防单侧删键）"
        )
        assert secrets_block["dispatch_token"]["required"] is False
        assert secrets_block["dispatch-token"]["required"] is False

    def test_job_topology(self) -> None:
        jobs = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]
        assert set(jobs.keys()) == {"resolve", "auto-merge"}
        assert jobs["auto-merge"].get("needs") == "resolve"
        matrix = jobs["auto-merge"]["strategy"]["matrix"]
        assert matrix["pr_number"] == "${{ fromJSON(needs.resolve.outputs.pr_numbers) }}"

    def test_merge_step_uses_consolidated_infra_core_action(self) -> None:
        """VAL-HARD-104：merge 步引用本仓 actions/auto-merge（shared-workflows 已退役）。"""
        steps = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]["auto-merge"]["steps"]
        merge_step = next(
            (s for s in steps if str(s.get("uses", "")).endswith("/actions/auto-merge@v0.7.2")),
            None,
        )
        assert merge_step is not None, "actions/auto-merge merge 步缺失"
        assert merge_step["uses"] == AUTO_MERGE_ACTION_REF, (
            f"merge 步必须引用本仓 actions/auto-merge@v0.7.2，实际: {merge_step['uses']}"
        )

    def test_no_shared_workflows_residual(self) -> None:
        """VAL-HARD-104：shared-workflows 退役后两载体零 live 引用（uses: 面，防回潮）。

        断言面是 step 的 uses: 引用（真正会被 GitHub 解析执行的部分）；
        注释中的移植溯源文字（含仓名+SHA）不算引用，允许保留。
        """
        for carrier in AUTO_MERGE_CARRIERS:
            offenders = [
                f"{job}: {step.get('uses')}"
                for job, step in _steps(_load_doc(carrier))
                if "shared-workflows" in str(step.get("uses", ""))
            ]
            assert not offenders, (
                f"{carrier.name} 残留 shared-workflows uses: 引用——该仓已退役归档，"
                f"merge action 在本仓 actions/auto-merge：{offenders}"
            )

    def test_merge_step_uses_dispatch_token_not_github_token(self) -> None:
        """合并凭证必须来自 dispatch_token secret 输入（PAT 防递归抑制），绝不回退 GITHUB_TOKEN。"""
        steps = _load_doc(AUTO_MERGE_PIPELINE_YML)["jobs"]["auto-merge"]["steps"]
        merge_step = next(
            s for s in steps if str(s.get("uses", "")).endswith("/actions/auto-merge@v0.7.2")
        )
        env = merge_step.get("env", {})
        assert env.get("GITHUB_TOKEN") == (
            "${{ secrets.dispatch_token || secrets['dispatch-token'] }}"
        ), (
            "merge 步 GITHUB_TOKEN env 必须经 dispatch_token 双形态熔合传入，"
            f"实际: {env.get('GITHUB_TOKEN')}"
        )

    def test_no_bare_snake_secret_consumption(self) -> None:
        """声明了 hyphen 变体的 snake 键，消费点一律熔合，禁止裸取（防漏熔合）。"""
        raw = AUTO_MERGE_PIPELINE_YML.read_text(encoding="utf-8")
        assert "${{ secrets.dispatch_token }}" not in raw, (
            "dispatch_token 存在裸取消费点——必须熔合 "
            "secrets.dispatch_token || secrets['dispatch-token']"
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


class TestAutoMergeCompositeActionContract:
    """VAL-HARD-104：actions/auto-merge composite action 移植契约。

    自 shared-workflows 仓 auto-merge action @5a0fc1b 行为等价移植
    （该仓已退役归档）。本类锁定移植保真面：composite 形态与
    元数据、零红扫描语义（全 check-runs 直查 + 四类非绿结论拦截）、
    squash + 删分支合并命令、凭证经 env GITHUB_TOKEN 注入（caller 侧铁律
    绑定 DISPATCH_TOKEN PAT，禁默认 GITHUB_TOKEN）。
    """

    ACTION_YML = REPO_ROOT / "actions/auto-merge/action.yml"

    def _load_action(self) -> dict[str, Any]:
        assert self.ACTION_YML.exists(), "actions/auto-merge/action.yml 必须存在"
        doc = yaml.safe_load(self.ACTION_YML.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), "action.yml 必须是 YAML mapping"
        return doc

    @staticmethod
    def _action_script(doc: dict[str, Any]) -> str:
        return " ".join(str(step.get("run", "")) for step in doc["runs"]["steps"])

    def test_composite_with_pr_number_input(self) -> None:
        doc = self._load_action()
        assert doc["name"] == "Auto Merge PR"
        assert doc["runs"]["using"] == "composite"
        inputs = doc.get("inputs") or {}
        assert inputs.get("pr-number", {}).get("required") is True
        assert inputs.get("pr-number", {}).get("type") == "string"

    def test_zero_red_scan_semantics_preserved(self) -> None:
        """零红铁律载体：merge 前全 check-runs 扫描（四类非绿结论全部拦截）。"""
        script = self._action_script(self._load_action())
        for conclusion in ("failure", "cancelled", "timed_out", "action_required"):
            assert conclusion in script, f"零红扫描缺少 {conclusion} 判定"
        assert "check-runs" in script, "必须直查 check-runs（含 advisory 层全量）"

    def test_squash_delete_branch_merge_command(self) -> None:
        script = self._action_script(self._load_action())
        assert "--squash" in script and "--delete-branch" in script, (
            "合并命令必须保持 gh pr merge --squash --delete-branch"
        )

    def test_credential_via_env_github_token(self) -> None:
        """composite 步凭证取自 env GITHUB_TOKEN——由 caller 注入 DISPATCH_TOKEN PAT。"""
        first = self._load_action()["runs"]["steps"][0]
        assert first.get("env", {}).get("GH_TOKEN") == "${{ env.GITHUB_TOKEN }}"

    def test_no_shared_workflows_reference(self) -> None:
        """action 内部 step 不得引用已退役仓（uses: 面；溯源注释不算）。"""
        doc = self._load_action()
        offenders = [
            step.get("uses")
            for step in doc["runs"]["steps"]
            if "shared-workflows" in str(step.get("uses", ""))
        ]
        assert not offenders, f"actions/auto-merge 内残留 shared-workflows 引用：{offenders}"
