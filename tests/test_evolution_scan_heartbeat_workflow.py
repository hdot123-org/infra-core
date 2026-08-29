"""Evolution scan/heartbeat reusable workflow 模板契约测试（M4，architecture.md §6）。

thin caller（消费仓）保留：文件名 evolution-scan.yml、schedule cron、workflow 名、
secrets 显式转发、事件触发面——由消费仓命名契约测试锁定；
本文件锁定 shipped reusable 模板：执行体步骤、环境契约（DISPATCH_TOKEN /
LINEAR_API_KEY / PYTHONSAFEPATH / pip install -e . / label-ensure / evolution-history
cache）、engine 经 ``python -m infra_core.engine.*`` 运行、以及 reusable 本身
**不得**携带 schedule（per-repo 定时，本期不中央化）。
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


def test_scan_reusable_triggers_call_only_no_schedule():
    """workflow_call + workflow_dispatch；schedule 禁止出现（per-repo 定时归 caller）。"""
    triggers = _triggers(_load(_SCAN))
    assert "workflow_call" in triggers, "reusable must expose workflow_call"
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers, "reusable 不得带 schedule——定时触发面属消费仓 thin caller"


def test_scan_reusable_secrets_contract():
    """VAL-GATE-113：secrets 显式声明（reusable 不隐式继承 caller secrets）。"""
    secrets = _triggers(_load(_SCAN))["workflow_call"]["secrets"]
    assert secrets["dispatch-token"]["required"] is True
    assert secrets["linear-api-key"]["required"] is False


def test_scan_reusable_job_permissions_and_runner():
    job = _load(_SCAN)["jobs"]["scan"]
    assert job["runs-on"] == ["self-hosted", "pve-linux"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}


def test_scan_reusable_env_contract():
    """VAL-GATE-108 环境契约：DISPATCH_TOKEN / LINEAR_API_KEY / PYTHONSAFEPATH 映射。"""
    steps = _scan_steps(_load(_SCAN))
    run_step = steps["Run evolution scanner"]
    env = run_step["env"]
    assert env["GH_TOKEN"] == "${{ secrets.dispatch-token }}"
    assert env["LINEAR_API_KEY"] == "${{ secrets.linear-api-key }}"
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
    assert ensure["env"]["GH_TOKEN"] == "${{ secrets.dispatch-token }}"
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


def test_heartbeat_reusable_triggers_call_only_no_schedule():
    triggers = _triggers(_load(_HEARTBEAT))
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers


def test_heartbeat_reusable_secrets_and_engine():
    """dispatch-token 必填 + 执行体为 infra-core heartbeat 引擎模块。"""
    data = _load(_HEARTBEAT)
    secrets = _triggers(data)["workflow_call"]["secrets"]
    assert secrets["dispatch-token"]["required"] is True
    job = data["jobs"]["heartbeat"]
    assert job["runs-on"] == ["self-hosted", "pve-linux"]
    run_step = {s.get("name", ""): s for s in job["steps"]}["Run heartbeat check"]
    assert run_step["run"] == "python -m infra_core.engine.evolution_heartbeat"
    assert run_step["env"]["GH_TOKEN"] == "${{ secrets.dispatch-token }}"
    assert run_step["env"]["PYTHONSAFEPATH"] == "1"


def test_heartbeat_reusable_label_ensure_heartbeat_label():
    steps = {s.get("name", ""): s for s in _load(_HEARTBEAT)["jobs"]["heartbeat"]["steps"]}
    ensure = steps["Ensure labels exist"]
    assert ensure["env"]["GH_TOKEN"] == "${{ secrets.dispatch-token }}"
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
    """
    for path in (_SCAN, _HEARTBEAT):
        data = _load(path)
        assert "concurrency" not in data, (
            f"{path.name} reusable 不得携带顶层 concurrency（自死锁陷阱）"
        )
