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
TRIAGE_SH = REPO_ROOT / "src/infra_core/shell/auto_merge_triage.sh"
GUARDED_CHECKOUT_WORKFLOWS = ("ci.yml", "qa.yml", "droid-review.yml")
GUARD_MARKER = 'rm -rf "$GITHUB_WORKSPACE/.git"'

SPARSE_CHECKOUT_KEYS = frozenset({"sparse-checkout", "sparse-checkout-cone-mode"})


def _load_doc() -> dict[str, Any]:
    doc = yaml.safe_load(AUTO_MERGE_YML.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "auto-merge.yml 必须是 YAML mapping"
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
    assert len(triage_steps) == 1, "auto-merge.yml 必须恰好包含一个 id=triage 的 run 步骤"
    return triage_steps[0]["run"]


class TestNoWorkspaceFootprint:
    def test_no_job_uses_actions_checkout(self) -> None:
        """防毒铁律：auto-merge.yml 全部 job 禁止 actions/checkout。

        checkout 是唯一会把 core.sparseCheckout=true 写进共享工作区
        .git/config 的入口；该 job 所需的 triage 脚本经 heredoc 内联，
        无需仓库工作区， checkout 必须整步移除而非仅去 sparse 参数。
        """
        offenders = [
            f"{job_name}: {step['uses']}"
            for job_name, step in _steps(_load_doc())
            if str(step.get("uses", "")).startswith("actions/checkout")
        ]
        assert not offenders, (
            "auto-merge.yml 禁止 actions/checkout（self-hosted 共享工作区防毒），"
            f"违规步骤: {offenders}"
        )

    def test_no_sparse_checkout_inputs_in_structure(self) -> None:
        """解析后的 workflow 结构不得出现任何 sparse-checkout 输入。"""
        keys = set(_iter_keys(_load_doc()))
        offenders = sorted(keys & SPARSE_CHECKOUT_KEYS)
        assert not offenders, f"workflow 结构含 sparse-checkout 输入: {offenders}"


class TestInlineTriageParity:
    def test_triage_heredoc_byte_identical_to_source(self) -> None:
        """heredoc 内联脚本必须与 src/ 源文件逐字节一致（防静默漂移）。"""
        run_script = _triage_run_script(_load_doc())
        match = re.search(r"<<'TRIAGE_EOF'\n(.*?)\nTRIAGE_EOF\n", run_script, re.DOTALL)
        assert match, "triage 步骤必须以 <<'TRIAGE_EOF' heredoc 内联脚本"
        inlined = match.group(1) + "\n"
        source = TRIAGE_SH.read_text(encoding="utf-8")
        assert inlined == source, (
            "auto-merge.yml 内联 triage 脚本与 "
            "src/infra_core/shell/auto_merge_triage.sh 漂移——两份必须同步修改"
        )

    def test_triage_invocation_targets_runner_temp(self) -> None:
        """triage 调用必须指向 RUNNER_TEMP，禁止工作区相对路径残留。"""
        run_script = _triage_run_script(_load_doc())
        assert 'bash "$RUNNER_TEMP/auto_merge_triage.sh"' in run_script, (
            "triage 必须经 $RUNNER_TEMP 调用内联脚本"
        )
        assert "bash src/infra_core/shell/auto_merge_triage.sh" not in run_script, (
            "triage 不得经工作区相对路径执行脚本（本 job 无工作区；注释中的路径引用不受限）"
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

    def test_automerge_job_first_step_is_guard(self) -> None:
        """auto-merge job 首步 = Workspace guard：每 sweep 三 runner 常驻自愈。"""
        doc = yaml.safe_load(AUTO_MERGE_YML.read_text(encoding="utf-8"))
        steps = doc["jobs"]["auto-merge"]["steps"]
        first = steps[0]
        assert "sparse" in str(first.get("name", "")), "auto-merge job 首步必须是 Workspace guard"
        assert GUARD_MARKER in str(first.get("run", "")), "guard 步骤必须包含排毒逻辑"
