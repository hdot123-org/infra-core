"""CI 结构契约测试（INFRA-580）

锁定 10-job 结构化 CI 的拓扑不变量，防止 bundle 化后的结构回退（lint/type/
advisory/test-groups 四个 bundle job 与六个独立 job 的集合完整性）、ci-ok
needs 漏配、advisory 被恢复 continue-on-error 掩蔽失败、marker 参数漂移、
runner 标签漂移、concurrency 语义漂移。

与 tests/test_naming_contract.py 的分工：naming_contract 锁既有 check 名的
字节级契约（architecture.md §2）；本文件锁结构层——job 集合完整性、ci-ok
依赖收口与逐项阻断、advisory 零红语义（INFRA-595：无 continue-on-error，
失败即红）、关键命令参数、PR 限定 cancel-in-progress。

2026-08-29 容量收敛（runner-capacity-one-shot）：19 job → 10 job——
lint-bundle（ruff/shellcheck/actionlint/repo-consistency）、type-bundle
（mypy×2）、advisory-bundle（advisory×3）、test-groups（schema/security/
business_policy 三段顺序）；pytest / integration-tests / e2e-tests /
guards / health-check / ci-ok 六个独立保持。
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_YML = REPO_ROOT / ".github/workflows/ci.yml"

# 11 个 job 的完整集合（19 → 10 容量收敛，2026-08-29；+1 notify-ci-complete
# webhook 注入，INFRA-569；快照只对齐当前 main：后续 ci.yml 变更由各自 feature
# 同步本表）
EXPECTED_JOBS = frozenset(
    {
        # 聚合锚点（命名契约：不可重命名，见 architecture.md §2）
        "pytest",
        # bundle（容量收敛四合一）
        "lint-bundle",
        "type-bundle",
        "advisory-bundle",
        "test-groups",
        # 独立 job
        "guards",
        "integration-tests",
        "e2e-tests",
        "health-check",
        # 聚合门禁（branch protection required check）
        "ci-ok",
        # CI 完成 webhook 通知（INFRA-569：对齐 memory 仓同构 job）
        "notify-ci-complete",
    }
)

ADVISORY_JOBS = frozenset({"advisory-bundle"})
# notify-ci-complete is a downstream notification job (needs ci-ok, not the
# other way around), so exclude it from BLOCKING_JOBS.
BLOCKING_JOBS = EXPECTED_JOBS - ADVISORY_JOBS - {"ci-ok", "notify-ci-complete"}

# 独立专项测试组 → marker
TEST_GROUP_MARKERS = {
    "integration-tests": "integration",
    "e2e-tests": "e2e",
}

# test-groups bundle 的三段 marker（顺序：schema → security → business_policy）
TEST_GROUPS_BUNDLE_MARKERS = ("schema", "security", "business_policy")

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
        """ci-ok 的 needs 必须收口全部 9 个前置 job（含 advisory-bundle，供结果透出）。"""
        needs = set(ci_jobs["ci-ok"].get("needs") or [])
        missing = (BLOCKING_JOBS | ADVISORY_JOBS) - needs
        assert not missing, f"ci-ok needs 缺失: {sorted(missing)}"

    def test_ci_ok_always_runs(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """聚合门禁必须 always() 运行：前置失败时 ci-ok 也要给出明确红叉。"""
        assert ci_jobs["ci-ok"].get("if") == "always()"


class TestConcurrencyContract:
    """2026-08-29 容量收敛的 concurrency 语义。

    PR 连环 push 取消同 ref 的进行中旧 run（省 pve 双机排队）；main push
    永不取消——合并后 main 全绿验证不能被后续事件打断（禁止裸 true）。
    """

    def test_concurrency_group_expression(self) -> None:
        doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        concurrency = doc.get("concurrency")
        assert isinstance(concurrency, dict), "ci.yml 必须声明顶层 concurrency"
        assert concurrency["group"] == "ci-${{ github.workflow }}-${{ github.ref }}"

    def test_cancel_in_progress_pr_only(self) -> None:
        """cancel-in-progress 必须是 PR 限定表达式，禁止裸 true。"""
        doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        concurrency = doc["concurrency"]
        assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}", (
            "cancel-in-progress 必须 PR 限定（裸 true 会打断合并后 main 全绿验证）"
        )


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

    def test_advisory_blocks_merge(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """用户铁律（2026-08-28）：写死不允许红色合并，一个都不允许。

        advisory jobs 必须被接入 ci-ok 阻断判定，任一红则不可合并。
        bundle 化后由 advisory-bundle 承接三个 advisory 的零红语义。

        INFRA-595：job 级 continue-on-error 会让 needs.<job>.result 恒为
        success（continue-on-error 之后的值），ci-ok 的 .result 判定沦为空转
        ——run 33129232081 实证：advisory-deptry check-run 为 failure 而
        .result 报 success。修复：移除 advisory 的 continue-on-error，
        使失败成为红 check-run，.result 判定与 GitHub API 全 check-runs
        扫描双保险均真实生效。
        """
        script = _job_run_script(ci_jobs, "ci-ok")
        for job in ADVISORY_JOBS:
            expected = (
                f'[[ "${{{{ needs.{job}.result }}}}" == "success" ]]'
                f' || {{ echo "FAIL: {job}"; FAILED=1; }}'
            )
            assert expected in script, f"advisory {job} 未接入阻断判定（违反零红铁律）"


class TestAdvisorySemantics:
    @pytest.mark.parametrize("job", sorted(ADVISORY_JOBS))
    def test_advisory_no_continue_on_error(
        self, ci_jobs: dict[str, dict[str, Any]], job: str
    ) -> None:
        """INFRA-595 零红铁律：advisory 不得设置 job 级 continue-on-error。

        continue-on-error 会（a）让 needs.<job>.result 恒为 success，ci-ok
        判定空转；（b）PR checks 面板显示为橙而非红。零红政策下 advisory
        失败必须直接阻断合并。
        """
        assert ci_jobs[job].get("continue-on-error") is None, (
            f"{job} 不得设置 continue-on-error（零红铁律：advisory 失败必须红）"
        )


class TestNotifyCiComplete:
    """notify-ci-complete webhook 通知契约（INFRA-690）。

    INFRA-690 要求 payload 同时携带 CI status 与 run URL：status 供
    trigger-ci-droid.sh 注入链判定绿红，run_url 供 n8n 下游自动化与
    人工排查直达 CI 运行页。#137 已落地 job 骨架但 payload 缺 run_url，
    本契约锁定该字段不可回退。
    """

    def test_notify_job_needs_ci_ok_and_always(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """通知 job 必须 needs ci-ok 且 always()：CI 红也要通知（下游
        需要感知失败并触发修复流程），仅限 PR 事件。"""
        job = ci_jobs["notify-ci-complete"]
        raw_needs = job.get("needs")
        needs = {raw_needs} if isinstance(raw_needs, str) else set(raw_needs or [])
        assert needs == {"ci-ok"}, "notify-ci-complete 必须 needs ci-ok（聚合后通知）"
        assert job.get("if") == "always() && github.event_name == 'pull_request'"

    def test_payload_includes_status_and_run_url(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """payload 必须同时含 status 与 run_url（INFRA-690 核心要求）。"""
        script = _job_run_script(ci_jobs, "notify-ci-complete")
        assert "needs.ci-ok.result" in script, "payload status 必须取自 ci-ok 结果"
        # run_url 源自 step env（github.run_id），run 脚本经 $RUN_URL 引用
        job_dump = yaml.safe_dump(ci_jobs["notify-ci-complete"], allow_unicode=True)
        assert "github.run_id" in job_dump, "payload 缺 run_url 源（github.run_id 未注入 env）"
        assert "run_url" in script, "payload 缺 run_url 字段"
        jq_build = "{repo:$repo, pr_number:$pr_number, branch:$branch, sha:$sha, status:$status, run_url:$run_url}"
        assert jq_build in script, "jq payload 构造缺 run_url 键（字段不可回退）"

    def test_delivery_failure_non_blocking_with_telemetry(
        self, ci_jobs: dict[str, dict[str, Any]]
    ) -> None:
        """通知失败不得阻断（exit 0 + PostHog 事件）：通知是旁路，红 CI
        不能因 webhook 投递失败而误报为通过。"""
        script = _job_run_script(ci_jobs, "notify-ci-complete")
        assert "ci_webhook_send_failed" in script, "投递失败必须上报 PostHog 事件"
        assert "exit 0" in script, "通知失败必须 exit 0（旁路语义）"

    def test_run_steps_use_strict_mode(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """INFRA-710：notify-ci-complete 全部 run 步骤必须 bash strict mode。

        PR #151 为 'Verify webhook secrets' 与 'Send CI status webhook'
        两个 run block 补齐 set -euo pipefail（bash 加固审计 finding），
        本契约锁定不可回退——webhook secret 验证与状态投递逻辑在宽松
        shell 下静默失败（未定义变量展开为空、管道半失败被吞），会直接
        破坏 n8n 注入链的可观测性与可诊断性。
        """
        steps = ci_jobs["notify-ci-complete"].get("steps") or []
        run_steps = [(idx, str(step["run"])) for idx, step in enumerate(steps) if "run" in step]
        assert run_steps, "notify-ci-complete 必须包含至少一个 run 步骤"
        for idx, script in run_steps:
            first_line = script.lstrip().splitlines()[0].strip()
            assert first_line == "set -euo pipefail", (
                f"notify-ci-complete 第 {idx} 个 run 步骤未启用 bash strict mode"
                f"（首行应为 set -euo pipefail，实际为 {first_line!r}）"
            )


class TestRunnerLabels:
    @pytest.mark.parametrize("job", sorted(EXPECTED_JOBS))
    def test_all_jobs_on_self_hosted_runner(
        self, ci_jobs: dict[str, dict[str, Any]], job: str
    ) -> None:
        runs_on = ci_jobs[job].get("runs-on")
        assert isinstance(runs_on, list), f"{job} runs-on 必须是标签列表"
        assert "self-hosted" in runs_on and "pve-linux" in runs_on, f"{job} runner 标签漂移"


class TestBundles:
    """bundle 化步骤语义保持（2026-08-29 容量收敛）。"""

    def test_lint_bundle_four_in_one(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """lint-bundle 必须四合一：ruff（check+format 两半）/ shellcheck /
        actionlint / repo-consistency，缺一即门禁降级。"""
        script = _job_run_script(ci_jobs, "lint-bundle")
        assert "ruff check ." in script
        assert "ruff format --check ." in script
        assert "shellcheck -x" in script
        assert "repo_health_check.sh --ci" in script

    def test_type_bundle_mypy_x2(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """type-bundle 必须 mypy×2：src 与 scripts 分域各跑一次
        （#61 bundle 化遗留的 Run mypy 重复步骤已去重，src 域禁止双跑）。"""
        script = _job_run_script(ci_jobs, "type-bundle")
        assert script.count("mypy --strict src/infra_core") == 1
        assert "mypy --strict scripts/" in script

    def test_advisory_bundle_three_in_one(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """advisory-bundle 必须三合一：pip-audit / deptry / 遥测覆盖率审计。"""
        script = _job_run_script(ci_jobs, "advisory-bundle")
        assert "pip-audit --progress-spinner off" in script
        assert "deptry ." in script
        assert "audit_telemetry_coverage.sh" in script

    def test_test_groups_three_segments_ordered(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """test-groups 三段 marker 顺序跑：schema → security → business_policy。"""
        script = _job_run_script(ci_jobs, "test-groups")
        positions = []
        for marker in TEST_GROUPS_BUNDLE_MARKERS:
            assert f"-m {marker}" in script, f"test-groups 缺失 -m {marker}"
            positions.append(script.index(f"-m {marker}"))
        assert positions == sorted(positions), (
            f"test-groups 三段顺序漂移：应为 {TEST_GROUPS_BUNDLE_MARKERS}"
        )


class TestTestGroups:
    @pytest.mark.parametrize("job,marker", sorted(TEST_GROUP_MARKERS.items()))
    def test_group_runs_marker_with_parallelism(
        self, ci_jobs: dict[str, dict[str, Any]], job: str, marker: str
    ) -> None:
        script = _job_run_script(ci_jobs, job)
        assert f"-m {marker}" in script, f"{job} 必须 按 marker 分组"
        assert "-n 4" in script, f"{job} 必须保持 4 worker 并行"
        assert "--no-cov" in script, f"{job} 专项组不重复计覆盖率（主 pytest job 已覆盖）"

    def test_bundle_segments_keep_parallelism_contract(
        self, ci_jobs: dict[str, dict[str, Any]]
    ) -> None:
        """test-groups 三段逐段保持 -n 4 + --no-cov 契约。"""
        script = _job_run_script(ci_jobs, "test-groups")
        assert script.count("-n 4") >= len(TEST_GROUPS_BUNDLE_MARKERS)
        assert script.count("--no-cov") >= len(TEST_GROUPS_BUNDLE_MARKERS)


class TestDomainMypy:
    def test_src_strict(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        assert "mypy --strict src/infra_core" in _job_run_script(ci_jobs, "type-bundle")

    def test_scripts_strict(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        assert "mypy --strict scripts/" in _job_run_script(ci_jobs, "type-bundle")


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


class TestActionlintHostFirst:
    """actionlint 步骤宿主优先契约（2026-08-29 node-00 raw 直连黑洞修复）。

    旧实现每 run 无条件 ``bash <(curl raw.githubusercontent.com/.../download-actionlint.bash)``
    ——curl 是非 git 直连，不走 runner insteadOf 镜像，node-00 出口对该域间歇黑洞
    （2026-08-29 03:23 实证 134s timeout，main CI run 33225582434/33231155505
    连续三轮红，仅剩此一条非镜像路径）。ce-01 runner 已预装
    /usr/local/bin/actionlint 1.7.11（Layer 1 就绪），契约：版本 ≥1.7 的宿主
    二进制直接使用，仅缺失/过旧时才允许 fallback 下载（GitHub-hosted 兼容）。

    2026-08-29 bundle 化后 actionlint 步骤位于 lint-bundle 内，契约不变。
    """

    def test_host_binary_probe_present(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """actionlint 步骤必须先探测宿主二进制（PATH 优先）。"""
        script = _job_run_script(ci_jobs, "lint-bundle")
        assert "command -v actionlint" in script, "缺少宿主二进制探测（PATH 优先分支）"

    def test_host_version_gate(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """宿主版本必须 ≥1.7 才直接使用（防过旧宿主二进制误用）。"""
        script = _job_run_script(ci_jobs, "lint-bundle")
        assert "-ge 7" in script, "缺少宿主版本 ≥1.7 门限判断"

    def test_fallback_download_warns(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """宿主缺失时 fallback 下载必须打 ::warning（异常态要显式暴露）。"""
        script = _job_run_script(ci_jobs, "lint-bundle")
        assert "::warning::actionlint not found on host" in script, "fallback 分支缺少 ::warning"

    def test_download_only_after_host_probe(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """curl 下载只允许存在于宿主探测之后（禁止恢复每 run 无条件首下载）。"""
        script = _job_run_script(ci_jobs, "lint-bundle")
        assert "download-actionlint.bash" in script, (
            "fallback 下载路径必须保留（GitHub-hosted 兼容）"
        )
        probe_at = script.index("command -v actionlint")
        download_at = script.index("download-actionlint.bash")
        assert probe_at < download_at, "下载路径出现在宿主探测之前（退化为无条件下载）"

    def test_invocation_keeps_color_flag(self, ci_jobs: dict[str, dict[str, Any]]) -> None:
        """lint 调用保持 actionlint -color（宿主与 fallback 两条路径一致）。"""
        script = _job_run_script(ci_jobs, "lint-bundle")
        assert "actionlint -color" in script
