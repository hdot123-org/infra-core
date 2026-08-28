"""auto-merge workflow 防毒契约测试（sparse-checkout 工作区污染回归锁定）

背景（2026-08-28 三 runner 污染事故，#48 回归）：auto-merge job 曾以
actions/checkout + sparse-checkout（cone-mode false）只取 triage 单文件。
GitHub-hosted runner 上工作区每 run 重建、无害；但 self-hosted 共享持久
工作区上，checkout 会把该工作区 .git/config 写成 core.sparseCheckout=true
并把工作树裁剪到极小集合——同一 runner 后续所有复用该工作区的 CI job 以
"Can't find action.yml under .github/actions/setup-venv" 失败，且每次
auto-merge 触发都重新污染（排毒三次后仍复发实证）。

本文件锁定四条不变量：
1. auto-merge.yml 任何 job 都不得使用 actions/checkout（该 job 零工作区足迹；
   防毒上优于"去 sparse-checkout 保留全量 checkout"）；
2. 解析后的 workflow 结构中不存在 sparse-checkout / sparse-checkout-cone-mode
   输入（注释中的禁令引用不出现在解析结构里，不影响本断言）；
3. 内联 triage 脚本与 src/infra_core/shell/auto_merge_triage.sh 逐字节一致
   （heredoc 副本禁止静默漂移——workflow 内联版是行为的唯一运行时来源，
   源文件是唯一编辑来源，两者必须同步演进）；
4. triage 调用指向 RUNNER_TEMP（每 run 独立、run 结束即清理），不引用
   工作区相对路径。
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
