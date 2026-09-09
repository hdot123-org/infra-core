"""P0-A 源感知守卫测试 — 验证三查逻辑（sentinel/runner/autofix 降级）"""

import subprocess
import tempfile
from pathlib import Path


def test_p0a_guard_proceed_no_sentinel():
    """测试：无 sentinel、非 runner 来源、AUTOFIX_AUTO_ENABLED=false → proceed"""
    guard_script = Path(__file__).parent.parent / "webhook-scripts" / "lib" / "p0a-guard.sh"
    test_script = f"""
source {guard_script}
_p0a_guard_run "123" "session" ""
echo $P0A_GUARD_RESULT
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )
    assert "proceed" in result.stdout, f"Expected 'proceed', got: {result.stdout}"


def test_p0a_guard_yield_sentinel():
    """测试：sentinel 存在 → yield（让路不开枪）"""
    guard_script = Path(__file__).parent.parent / "webhook-scripts" / "lib" / "p0a-guard.sh"
    test_script = f"""
export P0A_DRY_RUN=1
export P0A_DRY_RUN_SENTINEL=1
source {guard_script}
_p0a_guard_run "123" "session" ""
echo $P0A_GUARD_RESULT
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )
    assert "yield_sentinel" in result.stdout, f"Expected 'yield_sentinel', got: {result.stdout}"


def test_p0a_guard_silent_runner():
    """测试：source=runner → silent_runner（runner 来源静默通过）"""
    guard_script = Path(__file__).parent.parent / "webhook-scripts" / "lib" / "p0a-guard.sh"
    test_script = f"""
source {guard_script}
_p0a_guard_run "123" "runner" ""
echo $P0A_GUARD_RESULT
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )
    assert "silent_runner" in result.stdout, f"Expected 'silent_runner', got: {result.stdout}"


def test_p0a_guard_degraded_autofix():
    """测试：AUTOFIX_AUTO_ENABLED=true 且非 runner → degraded（降级为告警不开枪）"""
    guard_script = Path(__file__).parent.parent / "webhook-scripts" / "lib" / "p0a-guard.sh"
    test_script = f"""
export AUTOFIX_AUTO_ENABLED=true
source {guard_script}
_p0a_guard_run "123" "session" ""
echo $P0A_GUARD_RESULT
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )
    assert "alert_only" in result.stdout, f"Expected 'alert_only', got: {result.stdout}"


def test_p0a_guard_runner_overrides_autofix():
    """测试：runner 来源 + AUTOFIX_AUTO_ENABLED=true → silent_runner（runner 优先级更高）"""
    guard_script = Path(__file__).parent.parent / "webhook-scripts" / "lib" / "p0a-guard.sh"
    test_script = f"""
export AUTOFIX_AUTO_ENABLED=true
source {guard_script}
_p0a_guard_run "123" "runner" ""
echo $P0A_GUARD_RESULT
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )
    assert "silent_runner" in result.stdout, f"Expected 'silent_runner', got: {result.stdout}"


def test_p0a_guard_dry_run_no_sentinel():
    """测试：干跑模式，无 sentinel → proceed"""
    guard_script = Path(__file__).parent.parent / "webhook-scripts" / "lib" / "p0a-guard.sh"
    test_script = f"""
export P0A_DRY_RUN=1
export P0A_DRY_RUN_SENTINEL=0
source {guard_script}
_p0a_guard_run "123" "session" ""
echo $P0A_GUARD_RESULT
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )
    assert "proceed" in result.stdout, f"Expected 'proceed', got: {result.stdout}"
