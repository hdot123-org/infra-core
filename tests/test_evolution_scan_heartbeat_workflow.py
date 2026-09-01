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


def test_scan_reusable_pip_install_and_history_cache():
    """pip install -e .（VAL-GATE-108 环境契约）+ evolution-history run-scoped cache。"""
    steps = _scan_steps(_load(_SCAN))
    assert steps["Install package"]["run"] == "pip install -e ."
    cache = steps["Cache evolution history"]
    assert cache["uses"].startswith("actions/cache@")
    assert "evolution-history-${{ github.run_id }}" in cache["with"]["key"]
    assert cache["with"]["restore-keys"] == "evolution-history-"


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
