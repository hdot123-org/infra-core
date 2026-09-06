"""Evolution scan/heartbeat reusable workflow 模板契约测试（M4，architecture.md §6）。

thin caller（消费仓）保留：文件名 evolution-scan.yml、schedule cron、workflow 名、
secrets 显式转发、事件触发面——由消费仓命名契约测试锁定；
本文件锁定 shipped reusable 模板：执行体步骤、环境契约（DISPATCH_TOKEN /
LINEAR_API_KEY / PYTHONSAFEPATH / pip install -e . / label-ensure / evolution-history
cache）、engine 经 ``python -m infra_core.engine.*`` 运行、以及 INFRA-717 起的
引擎仓自扫 schedule 触发面（本仓自身作为自扫消费仓的定时面，见
test_*_self_scan_schedule）。
"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCAN = _REPO_ROOT / ".github" / "workflows" / "evolution-scan.yml"
_HEARTBEAT = _REPO_ROOT / ".github" / "workflows" / "evolution-heartbeat.yml"


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path.name} must parse to a mapping"
    return data


def _triggers(data: dict) -> dict:
    # YAML 1.1 parses bare 'on' as boolean True
    return data.get("on") or data.get(True) or {}


def _scan_steps(data: dict) -> dict[str, dict]:
    steps = data["jobs"]["scan"]["steps"]
    return {s.get("name", s.get("uses", "")): s for s in steps}


def test_scan_reusable_name_byte_exact():
    """reusable 模板名字节级（消费仓 caller 名 'Evolution Scan' 由消费仓测试锁定）。"""
    assert _load(_SCAN)["name"] == "Evolution Scan Reusable"


def test_scan_reusable_triggers_and_self_scan_schedule():
    """workflow_call + workflow_dispatch + 引擎仓自扫 schedule（INFRA-717）。

    schedule 面历史：M4 时点本测试曾断言 no-schedule（定时归消费仓 thin caller），
    但引擎仓自身作为消费仓无法建 thin caller（文件名被消费仓 uses 路径引用 +
    heartbeat SCANNER_WORKFLOW 按文件名探活双契约钉死），其自扫定时面一直漏建，
    全靠外部不规则 dispatch + heartbeat 自愈兜底——2026-09-01 INFRA-717 13h
    空窗严重告警的根因。schedule 仅在宿主仓生效，消费仓 caller 不受影响。
    """
    triggers = _triggers(_load(_SCAN))
    assert "workflow_call" in triggers, "reusable must expose workflow_call"
    assert "workflow_dispatch" in triggers
    schedule = triggers.get("schedule")
    assert schedule, "INFRA-717：引擎仓自扫必须自带 schedule（无 thin caller 可归属）"
    crons = [entry["cron"] for entry in schedule]
    assert crons == ["17,47 * * * *"], (
        f"自扫 cron 锚点漂移：{crons}（分钟位须避开 :00/:30 load-shed 窗，INFRA-578）"
    )


def test_scan_reusable_secrets_contract():
    """VAL-GATE-113：secrets 显式声明（reusable 不隐式继承 caller secrets）
    + 双形态键（CONSUMER-GATE-DEADLOCK 修复）：caller 未声明键即 run 级
    startup_failure，hyphen 变体必须并存且可选。"""
    secrets = _triggers(_load(_SCAN))["workflow_call"]["secrets"]
    assert secrets["dispatch_token"]["required"] is True
    assert secrets["linear_api_key"]["required"] is False
    # hyphen 过渡变体（memory #1075 双写 caller 期间 callee 必须接受两形态）
    assert secrets["dispatch-token"]["required"] is False
    assert secrets["linear-api-key"]["required"] is False


def test_scan_reusable_job_permissions_and_runner():
    job = _load(_SCAN)["jobs"]["scan"]
    assert job["runs-on"] == ["self-hosted", "pve-linux"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}


def test_scan_reusable_env_contract():
    """VAL-GATE-108 环境契约：DISPATCH_TOKEN / LINEAR_API_KEY / PYTHONSAFEPATH 映射
    （双形态熔合：secrets.x_snake || secrets['x-hyphen']）。"""
    steps = _scan_steps(_load(_SCAN))
    run_step = steps["Run evolution scanner"]
    env = run_step["env"]
    assert env["GH_TOKEN"] == "${{ secrets.dispatch_token || secrets['dispatch-token'] }}"
    assert env["LINEAR_API_KEY"] == "${{ secrets.linear_api_key || secrets['linear-api-key'] }}"
    assert env["PYTHONSAFEPATH"] == "1"


def test_scan_reusable_runs_infra_core_engine_module():
    """scanner 执行体必须是 infra-core 引擎模块（不可回退 scripts/ 相对路径）。"""
    steps = _scan_steps(_load(_SCAN))
    assert steps["Run evolution scanner"]["run"] == "python -m infra_core.engine.evolution_scanner"


def test_scan_reusable_generates_error_patterns_via_infra_entry():
    """'Generate error patterns' 步骤用 infra-core 入口（memory-error-patterns 随 M5 修剪）。"""
    steps = _scan_steps(_load(_SCAN))
    gen = steps["Generate error patterns"]
    assert gen["run"].strip() == "infra-error-patterns --all-projects"


def test_scan_reusable_step_order_generate_before_scan():
    """Generate error patterns 必须先于 Run evolution scanner（INFRA-81，顺序契约）。"""
    data = _load(_SCAN)
    names = [s.get("name", s.get("uses", "")) for s in data["jobs"]["scan"]["steps"]]
    assert names.index("Generate error patterns") < names.index("Run evolution scanner")


def test_scan_reusable_label_ensure_found_and_isolated():
    """label-ensure 契约：evolution-found FBCA04 / evolution-isolated B60205 + 显式 --repo。"""
    steps = _scan_steps(_load(_SCAN))
    ensure = steps["Ensure labels exist"]
    assert ensure["env"]["GH_TOKEN"] == "${{ secrets.dispatch_token || secrets['dispatch-token'] }}"
    run = ensure["run"]
    assert 'gh --repo "$GITHUB_REPOSITORY" label create "evolution-found" --color FBCA04' in run
    assert 'gh --repo "$GITHUB_REPOSITORY" label create "evolution-isolated" --color B60205' in run


def test_scan_reusable_conditional_install_and_history_cache():
    """Install package 是条件安装（pyproject.toml 守卫）+ evolution-history cache。

    v0.15.0 引擎解耦后，Install package 不再裸装消费仓，而是条件安装：
    Python 仓保留 inline audit_tools 契约；非 Python 仓跳过。
    """
    steps = _scan_steps(_load(_SCAN))
    install_run = steps["Install package"]["run"]
    # 条件安装语义：pyproject.toml 守卫 + skip echo + 无裸 pip install -e .
    assert "pyproject.toml" in install_run
    assert "pip install -e ." in install_run  # Python 仓路径保留
    assert "skip consumer install" in install_run
    # 非全等断言：步骤名保留但语义已是条件安装（非旧裸装）
    assert install_run != "pip install -e ."
    cache = steps["Cache evolution history"]
    assert cache["uses"].startswith("actions/cache@")
    assert "evolution-history-${{ github.run_id }}" in cache["with"]["key"]
    assert cache["with"]["restore-keys"] == "evolution-history-"


def test_scan_engine_install_step_uses_git_plus_at_engine_ref():
    """VAL-ENGINE-001：独立引擎安装步存在且用 git+ URL 带 ${ENGINE_REF}。"""
    steps = _scan_steps(_load(_SCAN))
    engine_step = steps["Install engine (same commit as this reusable workflow)"]
    run = engine_step["run"]
    assert "git+https://github.com/hdot123-org/infra-core.git@${ENGINE_REF}" in run
    assert "pip install" in run
    # 空断言 + 非 40-hex warning
    assert "test -n" in run
    assert "::warning::" in run


def test_scan_engine_ref_input_declared():
    """VAL-ENGINE-007：engine_ref 输入声明（optional string default ''）。"""
    triggers = _triggers(_load(_SCAN))
    wc = triggers["workflow_call"]
    inputs = wc.get("inputs") or {}
    assert "engine_ref" in inputs
    eng = inputs["engine_ref"]
    assert eng.get("required") is False
    assert eng.get("type") == "string"
    assert eng.get("default") == ""


def test_scan_ref_chain_exact_and_no_banned_properties():
    """VAL-ENGINE-002：解析链精确为 engine_ref || job.workflow_sha || github.sha；
    表达式级无 github.job_workflow_sha / github.action_ref / ref_name 用法（注释提及允许）。"""
    raw_scan = _SCAN.read_text()
    raw_hb = _HEARTBEAT.read_text()
    chain = "inputs.engine_ref || job.workflow_sha || github.sha"
    assert chain in raw_scan, "scan: 解析链缺失或变形"
    assert chain in raw_hb, "heartbeat: 解析链缺失或变形"
    # 表达式级禁用属性（排除 # 注释行）——三个禁用属性全覆盖
    import re

    banned = ["github.job_workflow_sha", "github.action_ref", "ref_name"]
    for raw in (raw_scan, raw_hb):
        lines = raw.splitlines()
        for line in lines:
            # 跳过纯注释行
            if re.match(r"^\s*#", line):
                continue
            # 跳过行内尾注释部分
            code_part = re.split(r"\s+#", line, maxsplit=1)[0]
            for prop in banned:
                assert prop not in code_part, f"禁用属性 {prop} 出现在表达式中: {line.strip()}"


def test_scan_provenance_assert_uses_commit_id_key():
    """VAL-ENGINE-003：断言步读 vcs_info.commit_id（PEP 610），40-hex 强比对。"""
    steps = _scan_steps(_load(_SCAN))
    assert_step = steps["Assert engine version and provenance"]
    run = assert_step["run"]
    assert "commit_id" in run
    assert 'vi.get("commit_id"' in run or "vi.get('commit_id'" in run
    # 不应使用错误键名 commit（v2.1 阻断教训）
    # 但注释中可能出现，需排除行首注释
    for line in run.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert 'vi.get("commit"' not in line and "vi.get('commit'" not in line, (
            f"错误键名 commit 出现于表达式: {line.strip()}"
        )


def test_heartbeat_engine_install_and_provenance_symmetry():
    """heartbeat 与 scan 同构：引擎安装步 + provenance 断言步必须存在。"""
    hb_steps = {s.get("name", ""): s for s in _load(_HEARTBEAT)["jobs"]["heartbeat"]["steps"]}
    assert "Install engine (same commit as this reusable workflow)" in hb_steps
    assert "Assert engine version and provenance" in hb_steps
    engine_run = hb_steps["Install engine (same commit as this reusable workflow)"]["run"]
    assert "git+https://github.com/hdot123-org/infra-core.git@${ENGINE_REF}" in engine_run
    provenance_run = hb_steps["Assert engine version and provenance"]["run"]
    assert "commit_id" in provenance_run


def test_heartbeat_conditional_install():
    """heartbeat 的 Install package 同样是条件安装。"""
    hb_steps = {s.get("name", ""): s for s in _load(_HEARTBEAT)["jobs"]["heartbeat"]["steps"]}
    install_run = hb_steps["Install package"]["run"]
    assert "pyproject.toml" in install_run
    assert "pip install -e ." in install_run
    assert "skip consumer install" in install_run
    assert install_run != "pip install -e ."


def test_heartbeat_engine_ref_input_declared():
    """heartbeat 同样声明 engine_ref 输入。"""
    triggers = _triggers(_load(_HEARTBEAT))
    wc = triggers["workflow_call"]
    inputs = wc.get("inputs") or {}
    assert "engine_ref" in inputs
    eng = inputs["engine_ref"]
    assert eng.get("required") is False


def test_actionlint_ignore_entries_exist():
    """VAL-ENGINE-005：.github/actionlint.yaml 含两 callee 的 workflow_sha ignore。"""
    actionlint_path = _REPO_ROOT / ".github" / "actionlint.yaml"
    assert actionlint_path.exists(), ".github/actionlint.yaml 必须存在"
    raw = actionlint_path.read_text()
    assert "workflow_sha" in raw
    assert "evolution-scan.yml" in raw
    assert "evolution-heartbeat.yml" in raw


def test_guard_sentinels_use_github_workflows_dir():
    """VAL-ENGINE-004：3 处哨兵探针为 .github/workflows，非 pyproject.toml。

    哨兵使用目录探测 (`-d`)，正则锚定 `-d` 字面量。按文件计数：
    droid-review-shards ×2、auto-merge-pipeline ×1，消除空转测试。
    """
    shards = (_REPO_ROOT / ".github" / "workflows" / "droid-review-shards.yml").read_text()
    am = (_REPO_ROOT / ".github" / "workflows" / "auto-merge-pipeline.yml").read_text()
    import re

    # 哨兵块中的探针表达式（目录探测 `-d`）
    guard_pattern = r'\[ ! -d "\$GITHUB_WORKSPACE/([^"]+)" \]'

    shards_matches = re.findall(guard_pattern, shards)
    am_matches = re.findall(guard_pattern, am)

    # 按文件计数：droid-review-shards 应有 2 处，auto-merge-pipeline 应有 1 处
    assert len(shards_matches) == 2, (
        f"droid-review-shards: 应有 2 处哨兵探针，实际 {len(shards_matches)}"
    )
    assert len(am_matches) == 1, f"auto-merge-pipeline: 应有 1 处哨兵探针，实际 {len(am_matches)}"

    # 所有探针均为 .github/workflows
    for name, matches in [
        ("droid-review-shards", shards_matches),
        ("auto-merge-pipeline", am_matches),
    ]:
        for m in matches:
            assert m == ".github/workflows", f"{name}: 哨兵探针应为 .github/workflows，实际为 {m}"


def test_file_header_contains_deprecated_chain_lessons():
    """VAL-ENGINE-006：文件头注释含弃用链教训（action_ref / job_workflow_sha / ref_name）。"""
    for path in (_SCAN, _HEARTBEAT):
        raw = path.read_text()
        # 文件头注释中必须提及这三个弃用属性（作为教训）
        assert "action_ref" in raw, f"{path.name}: 文件头缺 action_ref 弃用教训"
        assert "job_workflow_sha" in raw, f"{path.name}: 文件头缺 job_workflow_sha 弃用教训"
        assert "ref_name" in raw, f"{path.name}: 文件头缺 ref_name 弃用教训"
        # 旧引擎来源表述必须消除
        assert "连带安装" not in raw, f"{path.name}: 旧表述「连带安装」仍存"


def test_invariants_regression():
    """VAL-CROSS-003：改造不破坏既有契约（文件名/name/secrets/concurrency/schedule/permissions/python）。"""
    scan_data = _load(_SCAN)
    hb_data = _load(_HEARTBEAT)
    # (a) 文件名/name 字节级
    assert scan_data["name"] == "Evolution Scan Reusable"
    assert hb_data["name"] == "Evolution Heartbeat Reusable"
    # (b) secrets 双形态键
    scan_secrets = _triggers(scan_data)["workflow_call"]["secrets"]
    assert "dispatch_token" in scan_secrets
    assert "dispatch-token" in scan_secrets
    assert "linear_api_key" in scan_secrets
    assert "linear-api-key" in scan_secrets
    hb_secrets = _triggers(hb_data)["workflow_call"]["secrets"]
    assert "dispatch_token" in hb_secrets
    assert "dispatch-token" in hb_secrets
    # (c) callee 无顶层 concurrency
    assert "concurrency" not in scan_data
    assert "concurrency" not in hb_data
    # (d) INFRA-717 schedule
    scan_crons = [e["cron"] for e in _triggers(scan_data).get("schedule", [])]
    assert scan_crons == ["17,47 * * * *"]
    hb_crons = [e["cron"] for e in _triggers(hb_data).get("schedule", [])]
    assert hb_crons == ["53 */2 * * *"]
    # (e) 权限面不变量：顶层 permissions 与 job-level permissions 未扩权
    assert scan_data["permissions"] == {"contents": "read"}
    assert hb_data["permissions"] == {"contents": "read"}
    scan_job = scan_data["jobs"]["scan"]
    hb_job = hb_data["jobs"]["heartbeat"]
    assert scan_job["permissions"] == {"contents": "read", "issues": "write"}
    assert hb_job["permissions"] == {"contents": "read", "issues": "write"}
    # (e) Python 版本钉死：两文件均硬编码 python3.12（venv 创建步）
    scan_raw = _SCAN.read_text()
    hb_raw = _HEARTBEAT.read_text()
    assert "python3.12 -m venv" in scan_raw, "scan: Python 版本钉死值漂移"
    assert "python3.12 -m venv" in hb_raw, "heartbeat: Python 版本钉死值漂移"


def test_heartbeat_reusable_name_byte_exact():
    """reusable 模板名（消费仓 caller 名 'Evolution Heartbeat' 由消费仓测试锁定）。"""
    assert _load(_HEARTBEAT)["name"] == "Evolution Heartbeat Reusable"


def test_heartbeat_reusable_triggers_and_self_scan_schedule():
    """workflow_call + workflow_dispatch + 引擎仓自扫心跳 schedule（INFRA-717）。

    同 scan 侧：本仓自扫心跳无 thin caller 可归属（探活按本文件名解析 run
    历史），自带 schedule 恢复定时面。重复 tick 无害（自愈幂等）。
    """
    triggers = _triggers(_load(_HEARTBEAT))
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers
    schedule = triggers.get("schedule")
    assert schedule, "INFRA-717：引擎仓自扫心跳必须自带 schedule"
    crons = [entry["cron"] for entry in schedule]
    assert crons == ["53 */2 * * *"], f"自扫心跳 cron 锚点漂移：{crons}"


def test_heartbeat_reusable_secrets_and_engine():
    """dispatch_token 必填（M5 R1(3) snake_case）+ 双形态 hyphen 变体 + 执行体为
    infra-core heartbeat 引擎模块。"""
    data = _load(_HEARTBEAT)
    secrets = _triggers(data)["workflow_call"]["secrets"]
    assert secrets["dispatch_token"]["required"] is True
    assert secrets["dispatch-token"]["required"] is False, (
        "必须声明 hyphen 过渡变体 dispatch-token（双形态并存，防单侧删键）"
    )
    job = data["jobs"]["heartbeat"]
    assert job["runs-on"] == ["self-hosted", "pve-linux"]
    run_step = {s.get("name", ""): s for s in job["steps"]}["Run heartbeat check"]
    assert run_step["run"] == "python -m infra_core.engine.evolution_heartbeat"
    assert (
        run_step["env"]["GH_TOKEN"] == "${{ secrets.dispatch_token || secrets['dispatch-token'] }}"
    )
    assert run_step["env"]["PYTHONSAFEPATH"] == "1"


def test_heartbeat_reusable_label_ensure_heartbeat_label():
    steps = {s.get("name", ""): s for s in _load(_HEARTBEAT)["jobs"]["heartbeat"]["steps"]}
    ensure = steps["Ensure labels exist"]
    assert ensure["env"]["GH_TOKEN"] == "${{ secrets.dispatch_token || secrets['dispatch-token'] }}"
    assert (
        'gh --repo "$GITHUB_REPOSITORY" label create "evolution-heartbeat" --color D93F0B'
        in ensure["run"]
    )


def test_reusable_must_not_carry_concurrency():
    """reusable 本体禁止顶层 concurrency（caller 同名组 → GitHub 自死锁秒取消）。

    实测（2026-08-29，memory #1071 切换首 tick）：caller 顶层 group
    'evolution-scan' 与 callee 内 'evolution-scan' 同名时，run 级 deadlock
    检测直接取消、零 job（"Canceling since a deadlock was detected for
    concurrency group ... between a top level workflow and 'scan'"）。
    per-repo 串行化归 caller 顶层 concurrency（消费仓契约测试锁定）。

    注：全量 workflow_call 泛化禁令见 test_naming_contract.py
    TestReusableNoTopLevelConcurrency（INFRA-626）。
    """
    for path in (_SCAN, _HEARTBEAT):
        data = _load(path)
        assert "concurrency" not in data, (
            f"{path.name} reusable 不得携带顶层 concurrency（自死锁陷阱）"
        )
