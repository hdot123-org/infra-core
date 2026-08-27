"""CI 结构契约测试（INFRA-580）

锁定 14-job 结构化 CI 的拓扑不变量，防止 guards / 专项测试组 / 分域 mypy /
advisory job 被静默删除或降级（ci-ok needs 漏配、advisory 变阻塞、marker
参数漂移、runner 标签漂移）。

与 tests/test_naming_contract.py 的分工：naming_contract 锁既有 check 名的
字节级契约（architecture.md §2）；本文件锁结构层——job 集合完整性、ci-ok
依赖收口与逐项阻断、advisory 非阻塞语义、关键命令参数。
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_YML = REPO_ROOT / ".github/workflows/ci.yml"

# 14 个 job 的完整集合（6 → 14 扩展，INFRA-580）
EXPECTED_JOBS = frozenset(
    {
        # 既有 job（命名契约：不可重命名，见 architecture.md §2）
        "pytest",
        "ruff",
        "actionlint",
        "mypy",
        # guards（4 个守卫脚本统一执行）
        "guards",
        # 专项测试组（pytest markers 分组）
        "security-tests",
        "schema-tests",
        "integration-tests",
        "e2e-tests",
        # 分域 mypy（--strict）
        "mypy-src-strict",
        "mypy-scripts-strict",
        # advisory（非阻塞，continue-on-error）
        "advisory-dependency-security-scan",
        "advisory-deptry",
        # 聚合门禁（branch protection required check）
        "ci-ok",
    }
)

ADVISORY_JOBS = frozenset({"advisory-dependency-security-scan", "advisory-deptry"})
BLOCKING_JOBS = EXPECTED_JOBS - ADVISORY_JOBS - {"ci-ok"}

TEST_GROUP_MARKERS = {
    "security-tests": "security",
    "schema-tests": "schema",
    "integration-tests": "integration",
    "e2e-tests": "e2e",
}

GUARD_SCRIPTS = (
    "scripts/check_boundary.py",
    "scripts/check_doc_classification.py",
    "scripts/check_fix_has_test.py",
    "scripts/check_pr_ref_consistency.py",
)


def _load_jobs() -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "ci.yml 必须是 YAML mapping"
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict), "ci.yml 必须定义 jobs mapping"
    return jobs


@pytest.fixture(scope="module")
def ci_jobs() -> dict[str, dict[str, Any]]:
    return _load_jobs()


def _job_run_script(jobs: dict[str, dict[str, Any]], job: str) -> str:
    """拼接某 job 全部 run 步骤的脚本文本（YAML block scalar 已去缩进）。"""
    steps = jobs[job].get("steps") or []
    runs = [str(step["run"]) for step in steps if "run" in step]
    assert runs, f"{job} 必须包含至少一个 run 步骤"
    return "\n".join(runs)


class TestJobTopology:
    def test_expected_job_set_present(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """job 集合精确匹配：静默删除/新增 job 都会触发本契约。"""
        assert frozenset(ci_jobs) == EXPECTED_JOBS

    def test_ci_ok_needs_all_blocking_jobs(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """ci-ok 的 needs 必须收口全部 12 个前置 job（含 advisory，供结果透出）。"""
        needs = set(ci_jobs["ci-ok"].get("needs") or [])
        missing = (BLOCKING_JOBS | ADVISORY_JOBS) - needs
        assert not missing, f"ci-ok needs 缺失: {sorted(missing)}"

    def test_ci_ok_always_runs(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """聚合门禁必须 always() 运行：前置失败时 ci-ok 也要给出明确红叉。"""
        assert ci_jobs["ci-ok"].get("if") == "always()"


class TestCiOkEnforcement:
    def test_each_blocking_job_enforced(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """needs 只是等待关系；每个阻塞 job 必须在聚合脚本中被显式判定。"""
        script = _job_run_script(ci_jobs, "ci-ok")
        for job in sorted(BLOCKING_JOBS):
            expected = (
                f'[[ "${{{{ needs.{job}.result }}}}" == "success" ]] '
                f'|| {{ echo "FAIL: {job}"; FAILED=1; }}'
            )
            assert expected in script, f"ci-ok 未显式阻断 {job}（缺失逐项判定行）"

    def test_advisory_never_blocks(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """advisory 结果行只允许 echo 透出，禁止出现在判定/FAIL 行中。"""
        script = _job_run_script(ci_jobs, "ci-ok")
        for line in script.splitlines():
            for job in ADVISORY_JOBS:
                if f"needs.{job}.result" in line:
                    assert "FAIL" not in line, f"advisory {job} 被接入阻断判定"
                    assert "[[" not in line, f"advisory {job} 被接入条件判定"


class TestAdvisorySemantics:
    @pytest.mark.parametrize("job", sorted(ADVISORY_JOBS))
    def test_advisory_continue_on_error(self, ci_jobs: dict[str, dict[str, Any]], job: str) -> None:
        assert ci_jobs[job].get("continue-on-error") is True, f"{job} 必须保持非阻塞"


class TestRunnerLabels:
    @pytest.mark.parametrize("job", sorted(EXPECTED_JOBS))
    def test_all_jobs_on_self_hosted_runner(
        self, ci_jobs: dict[str, dict[str, Any]], job: str
    ) -> None:
        runs_on = ci_jobs[job].get("runs-on")
        assert isinstance(runs_on, list), f"{job} runs-on 必须是标签列表"
        assert "self-hosted" in runs_on and "pve-linux" in runs_on, f"{job} runner 标签漂移"


class TestTestGroups:
    @pytest.mark.parametrize("job,marker", sorted(TEST_GROUP_MARKERS.items()))
    def test_group_runs_marker_with_parallelism(
        self, ci_jobs: dict[str, dict[str, Any]], job: str, marker: str
    ) -> None:
        script = _job_run_script(ci_jobs, job)
        assert f"-m {marker}" in script, f"{job} 必须 按 marker 分组"
        assert "-n 4" in script, f"{job} 必须保持 4 worker 并行"
        assert "--no-cov" in script, f"{job} 专项组不重复计覆盖率（主 pytest job 已覆盖）"


class TestDomainMypy:
    def test_src_strict(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        assert "mypy --strict src/infra_core" in _job_run_script(ci_jobs, "mypy-src-strict")

    def test_scripts_strict(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        assert "mypy --strict scripts/" in _job_run_script(ci_jobs, "mypy-scripts-strict")


class TestExistingJobInvariants:
    def test_pytest_main_command_unchanged(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """主 pytest job 铁律：-n 8 --dist loadgroup + 覆盖率地板（ramp-up 见 pyproject）。"""
        script = _job_run_script(ci_jobs, "pytest")
        assert "-n 8" in script and "--dist loadgroup" in script
        assert "--cov-fail-under=45" in script

    def test_guards_run_all_four_guard_scripts(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        script = _job_run_script(ci_jobs, "guards")
        for guard_script in GUARD_SCRIPTS:
            assert f"python {guard_script}" in script, f"guards 缺失 {guard_script}"

    def test_e2e_includes_cli_smoke(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        assert "scripts/cli_smoke_test.sh" in _job_run_script(ci_jobs, "e2e-tests")
