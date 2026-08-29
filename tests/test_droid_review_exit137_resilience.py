"""exit 137 完成期竞态韧性回归测试（2026-08-29 #40/#45/#47 多次实证）。

故障链（run 33226955612 debug artifact 实证）：
droid exec 完成审查（session jsonl 最后一行已是完整 findings JSON）但在最终
stdout flush 前被 SIGKILL（137）→ tee 捕获 0 字节 → 原『非零退出但有有效输出
则继续』守卫失效（stdout 空）→ fail-closed → PR 假红。无 OOM（memory.events
全 0）、无 cancel，重跑约 50% 恢复。

修复三路（fail-closed 语义保留——stdout 与会话两路皆空才红）：
(1) exit 137 且 stdout 空 → 同参数单次重试；
(2) stdout 不可用 → 从本 run 的 session jsonl（~/.factory/sessions/<cwd 拍平>/
    <session-id>.jsonl 最后一行 assistant text 的 ```json 块）恢复 findings，
    ::warning 标注来源；候选会话必须同时满足 mtime ≥ 本次 exec 启动时刻、
    含本 run 唯一 prompt 标记、shard_id 匹配、findings 为合法数组；
(3) 两路皆空才 fail-closed。
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "src" / "infra_core" / "engine" / "droid_review"
ENGINE_RUN_SHARD = ENGINE_DIR / "run_shard.sh"
ENGINE_RECOVER_HELPER = ENGINE_DIR / "recover_shard_findings.sh"
CI_RUN_SHARD = REPO_ROOT / "scripts" / "droid_review" / "run_shard.sh"
CI_PUBLISH_FINDINGS = REPO_ROOT / "scripts" / "droid_review" / "publish_findings.py"

RUN_ID = "777000"
SHARD_ID = "0"
MARKER = f"droid-review-shard-marker:{RUN_ID}-{SHARD_ID}"
FINDINGS = {
    "shard_id": 0,
    "findings": [
        {"severity": "P2", "file": "a.py", "line": 3, "message": "边界检查缺失"},
        {"severity": "P3", "file": "a.py", "line": 9, "message": "命名不清晰"},
    ],
}
# stdout 成功路径用不同 message，区分 findings 到底来自 stdout 还是会话恢复
STDOUT_FINDINGS = {
    "shard_id": 0,
    "findings": [
        {"severity": "P1", "file": "a.py", "line": 3, "message": "stdout 路径特有发现"},
    ],
}

FAKE_DROID_PY = r"""#!/usr/bin/env python3
import json, os, sys, uuid

with open(os.environ["FAKE_DROID_CONFIG"]) as f:
    cfg = json.load(f)

n = 0
if os.path.exists(cfg["calls_file"]):
    n = int(open(cfg["calls_file"]).read().strip() or "0")
n += 1
with open(cfg["calls_file"], "w") as f:
    f.write(str(n))

attempts = cfg["attempts"]
attempt = attempts[n - 1] if n <= len(attempts) else attempts[-1]

args = sys.argv[1:]
cwd = "."
for i, a in enumerate(args):
    if a == "--cwd":
        cwd = args[i + 1]
        break

if attempt.get("write_session"):
    sdir = os.path.join(cfg["sessions_dir"], cwd.replace("/", "-"))
    os.makedirs(sdir, exist_ok=True)
    sid = str(uuid.uuid4())
    marker = "droid-review-shard-marker:%s-%s" % (cfg["run_id"], cfg["shard_id"])
    lines = [
        json.dumps({"type": "session_start", "id": sid, "cwd": cwd}),
        json.dumps({"type": "message", "message": {"role": "user", "content": [
            {"type": "text", "text": "Prompt containing " + marker}]}}),
    ]
    if attempt.get("session_complete", True):
        text = "Review result:\n```json\n" + json.dumps(cfg["findings"], indent=2) + "\n```\n"
    else:
        # 模拟 SIGKILL 落在 findings JSON 写一半：闭合围栏但内容截断
        broken = '{"shard_id": 0, "findings": [{"severi'
        text = "Review result:\n```json\n" + broken + "\n```\n"
    lines.append(json.dumps({"type": "message", "message": {"role": "assistant", "content": [
        {"type": "text", "text": text}]}}))
    with open(os.path.join(sdir, sid + ".jsonl"), "w") as f:
        f.write("\n".join(lines) + "\n")

mode = attempt["mode"]
if mode == "exit137":
    sys.exit(137)
if mode == "exit0_silent":
    sys.exit(0)
if mode == "exit1":
    sys.exit(1)
if mode == "success":
    print(json.dumps(cfg["stdout_findings"]))
    sys.exit(0)
if mode == "exit137_with_stdout":
    print(json.dumps(cfg["stdout_findings"]))
    sys.exit(137)
sys.exit(1)
"""


def flatten_cwd(cwd: str) -> str:
    """与 Factory 会话存储一致：cwd 中 / 替换为 -（实证 run 33226955612）。"""
    return cwd.replace("/", "-")


def write_session(
    sessions_dir: Path,
    cwd: str,
    findings: dict | None,
    *,
    marker: str | None = MARKER,
    complete: bool = True,
    mtime: float | None = None,
    session_id: str | None = None,
) -> Path:
    """构造一个 Factory session jsonl（结构与实证 artifact 一致）。"""
    sdir = sessions_dir / flatten_cwd(cwd)
    sdir.mkdir(parents=True, exist_ok=True)
    sid = session_id or str(uuid.uuid4())
    lines: list[dict] = [{"type": "session_start", "id": sid, "cwd": cwd}]
    if marker is not None:
        lines.append(
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": f"Prompt containing {marker}"}],
                },
            }
        )
    if findings is not None:
        if complete:
            text = "Review result:\n```json\n" + json.dumps(findings, indent=2) + "\n```\n"
        else:
            broken = '{"shard_id": 0, "findings": [{"severi'
            text = "Review result:\n```json\n" + broken + "\n```\n"
        lines.append(
            {
                "type": "message",
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
            }
        )
    p = sdir / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


@pytest.fixture
def shard_sandbox(tmp_path: Path) -> SimpleNamespace:
    """构造 run_shard.sh 可独立执行的 workspace：
    .github/review/shard-review-prompt.md + scripts/droid_review/publish_findings.py
    + head-src git 仓库（两 commit，产生非空 diff）。
    """
    ws = tmp_path / "ws"
    (ws / ".github" / "review").mkdir(parents=True)
    (ws / ".github" / "review" / "shard-review-prompt.md").write_text(
        "You are reviewing a shard. Return only valid JSON.\n", encoding="utf-8"
    )
    scripts_dir = ws / "scripts" / "droid_review"
    scripts_dir.mkdir(parents=True)
    shutil.copy(CI_PUBLISH_FINDINGS, scripts_dir / "publish_findings.py")

    head = ws / "head-src"
    head.mkdir()
    git_cfg = tmp_path / "git-config"
    git_cfg.write_text("", encoding="utf-8")

    def git(*args: str) -> str:
        env = os.environ.copy()
        env["GIT_CONFIG_GLOBAL"] = str(git_cfg)
        env["GIT_CONFIG_SYSTEM"] = str(git_cfg)
        r = subprocess.run(
            ["git", "-C", str(head), *args], env=env, check=True, capture_output=True, text=True
        )
        return r.stdout.strip()

    git("init", "-q")
    (head / "a.py").write_text("def f(x):\n    return x / 0\n", encoding="utf-8")
    git("add", "a.py")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    base_sha = git("rev-parse", "HEAD")
    (head / "a.py").write_text("def f(x):\n    return x // 0\n", encoding="utf-8")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-am", "head")
    head_sha = git("rev-parse", "HEAD")

    return SimpleNamespace(ws=ws, head=head, base_sha=base_sha, head_sha=head_sha, git_cfg=git_cfg)


def install_fake_droid(sandbox: SimpleNamespace, attempts: list[dict], sessions_dir: Path) -> Path:
    bin_dir = sandbox.ws / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    droid = bin_dir / "droid"
    droid.write_text(FAKE_DROID_PY, encoding="utf-8")
    droid.chmod(0o755)
    cfg = {
        "attempts": attempts,
        "calls_file": str(sandbox.ws / "fake-droid-calls"),
        "sessions_dir": str(sessions_dir),
        "findings": FINDINGS,
        "stdout_findings": STDOUT_FINDINGS,
        "run_id": RUN_ID,
        "shard_id": SHARD_ID,
    }
    cfg_path = sandbox.ws / "fake-droid-config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path


def run_run_shard(
    sandbox: SimpleNamespace,
    sessions_dir: Path,
    cfg_path: Path,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_WORKSPACE": str(sandbox.ws),
            "SHARD_ID": SHARD_ID,
            "SHARD_FILES": json.dumps(["a.py"]),
            "BASE_REF": sandbox.base_sha,
            "HEAD_REF": sandbox.head_sha,
            "MERGE_BASE": sandbox.base_sha,
            "RUN_ID": RUN_ID,
            "FACTORY_SESSIONS_DIR": str(sessions_dir),
            "FAKE_DROID_CONFIG": str(cfg_path),
            "GIT_CONFIG_GLOBAL": str(sandbox.git_cfg),
            "GIT_CONFIG_SYSTEM": str(sandbox.git_cfg),
            "PATH": f"{sandbox.ws / 'fakebin'}:{env['PATH']}",
            # scripts/droid_review/publish_findings.py wrapper 需要 infra_core 包
            "PYTHONPATH": str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    return subprocess.run(
        ["bash", str(CI_RUN_SHARD)],
        cwd=str(sandbox.ws),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def droid_calls(sandbox: SimpleNamespace) -> int:
    calls = sandbox.ws / "fake-droid-calls"
    return int(calls.read_text().strip()) if calls.exists() else 0


# ════════════════════════════════════════════════════════════════════════
# Part A: run_shard.sh 端到端（重试 + 会话兜底 + fail-closed）
# ════════════════════════════════════════════════════════════════════════


class TestRunShardResilienceE2E:
    def test_01_137_empty_retries_once_then_recovers_from_session(self, shard_sandbox):
        """exit 137 + 空 stdout：单次重试；重试仍 137 但会话完整 → 会话恢复（warning 标注）。"""
        sessions_dir = shard_sandbox.ws / "factory-sessions"
        sessions_dir.mkdir()
        attempts = [
            {"mode": "exit137", "write_session": True, "session_complete": True},
            {"mode": "exit137"},
        ]
        cfg = install_fake_droid(shard_sandbox, attempts, sessions_dir)
        r = run_run_shard(shard_sandbox, sessions_dir, cfg)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert droid_calls(shard_sandbox) == 2, "exit 137 空 stdout 必须恰好重试一次"
        out = json.loads((shard_sandbox.ws / f"findings-shard-{SHARD_ID}.json").read_text())
        assert out == FINDINGS, "恢复的 findings 必须来自会话（两次尝试 stdout 均空）"
        combined = r.stdout + r.stderr
        assert "retrying once" in combined, "必须打重试日志"
        assert "::warning" in combined and "session jsonl" in combined, (
            "恢复必须 ::warning 标注来源"
        )

    def test_02_137_retry_success_uses_stdout(self, shard_sandbox):
        """第一次 137 空 stdout，重试成功 → 走 stdout 正常路径。"""
        sessions_dir = shard_sandbox.ws / "factory-sessions"
        sessions_dir.mkdir()
        attempts = [{"mode": "exit137"}, {"mode": "success"}]
        cfg = install_fake_droid(shard_sandbox, attempts, sessions_dir)
        r = run_run_shard(shard_sandbox, sessions_dir, cfg)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert droid_calls(shard_sandbox) == 2
        out = json.loads((shard_sandbox.ws / f"findings-shard-{SHARD_ID}.json").read_text())
        assert out == STDOUT_FINDINGS, "重试成功时 findings 必须来自 stdout"

    def test_03_137_twice_no_session_fails_closed(self, shard_sandbox):
        """两路皆空（stdout 空 + 无有效会话）→ fail-closed，且重试恰好一次。"""
        sessions_dir = shard_sandbox.ws / "factory-sessions"
        sessions_dir.mkdir()
        attempts = [{"mode": "exit137"}, {"mode": "exit137"}]
        cfg = install_fake_droid(shard_sandbox, attempts, sessions_dir)
        r = run_run_shard(shard_sandbox, sessions_dir, cfg)
        assert r.returncode != 0, "两路皆空必须 fail-closed"
        assert droid_calls(shard_sandbox) == 2, "fail-closed 前仍必须先重试一次"
        assert "fail-closed" in (r.stdout + r.stderr)

    def test_04_non_137_failure_does_not_retry(self, shard_sandbox):
        """非 137 失败不触发重试（保持原语义，直接走兜底/fail-closed）。"""
        sessions_dir = shard_sandbox.ws / "factory-sessions"
        sessions_dir.mkdir()
        cfg = install_fake_droid(shard_sandbox, [{"mode": "exit1"}], sessions_dir)
        r = run_run_shard(shard_sandbox, sessions_dir, cfg)
        assert r.returncode != 0
        assert droid_calls(shard_sandbox) == 1, "非 137 失败不得重试"

    def test_05_137_with_valid_stdout_skips_retry(self, shard_sandbox):
        """exit 137 但 stdout 有效（torn flush 前）→ 原有 warn-continue 路径，不重试。"""
        sessions_dir = shard_sandbox.ws / "factory-sessions"
        sessions_dir.mkdir()
        cfg = install_fake_droid(shard_sandbox, [{"mode": "exit137_with_stdout"}], sessions_dir)
        r = run_run_shard(shard_sandbox, sessions_dir, cfg)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert droid_calls(shard_sandbox) == 1, "stdout 已有效时不得重试"
        out = json.loads((shard_sandbox.ws / f"findings-shard-{SHARD_ID}.json").read_text())
        assert out == STDOUT_FINDINGS

    def test_06_exit0_empty_stdout_goes_session_recovery_first(self, shard_sandbox):
        """exit 0 但 stdout 空（flush 丢失变体）→ 先会话兜底，两路皆空才红。"""
        sessions_dir = shard_sandbox.ws / "factory-sessions"
        sessions_dir.mkdir()
        attempts = [{"mode": "exit0_silent", "write_session": True, "session_complete": True}]
        cfg = install_fake_droid(shard_sandbox, attempts, sessions_dir)
        r = run_run_shard(shard_sandbox, sessions_dir, cfg)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert droid_calls(shard_sandbox) == 1, "exit 0 不触发 137 重试"
        out = json.loads((shard_sandbox.ws / f"findings-shard-{SHARD_ID}.json").read_text())
        assert out == FINDINGS, "stdout 空 + 会话完整 → 使用会话产物"


# ════════════════════════════════════════════════════════════════════════
# Part B: recover_shard_findings.sh 单元（候选选择规则）
# ════════════════════════════════════════════════════════════════════════


def run_helper(
    sandbox: SimpleNamespace,
    sessions_dir: Path,
    cwd: str,
    start_epoch: int,
    out_file: Path,
    run_id: str = RUN_ID,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "FACTORY_SESSIONS_DIR": str(sessions_dir),
            "RUN_ID": run_id,
        }
    )
    return subprocess.run(
        ["bash", str(ENGINE_RECOVER_HELPER), cwd, str(start_epoch), SHARD_ID, str(out_file)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestRecoverHelper:
    def _sandbox(self, tmp_path: Path) -> SimpleNamespace:
        ws = tmp_path / "ws"
        ws.mkdir()
        return SimpleNamespace(ws=ws)

    def test_11_picks_newest_matching_session_among_candidates(self, tmp_path):
        """候选按最新优先迭代：最新会话 shard_id 不匹配时回退到较旧的正确会话。"""
        sandbox = self._sandbox(tmp_path)
        sessions_dir = sandbox.ws / "sessions"
        cwd = "/var/lib/runner/_work/repo/repo/head-src"
        now = time.time()
        # 较旧：正确 shard
        write_session(sessions_dir, cwd, FINDINGS, mtime=now - 30, session_id="aaaa-old")
        # 最新：错误 shard（同机并行 shard 的会话）
        write_session(
            sessions_dir, cwd, {**FINDINGS, "shard_id": 1}, mtime=now, session_id="bbbb-new"
        )
        out = sandbox.ws / "recovered.json"
        r = run_helper(sandbox, sessions_dir, cwd, int(now) - 60, out)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert json.loads(out.read_text()) == FINDINGS, "必须跳过 shard_id 不匹配的最新候选"

    def test_12_rejects_truncated_session_json(self, tmp_path):
        """围栏闭合但 JSON 截断（SIGKILL 落在写一半）→ 拒绝该候选 → fail-closed。"""
        sandbox = self._sandbox(tmp_path)
        sessions_dir = sandbox.ws / "sessions"
        cwd = "/tmp/x/head-src"
        now = time.time()
        write_session(sessions_dir, cwd, FINDINGS, complete=False, mtime=now)
        out = sandbox.ws / "recovered.json"
        r = run_helper(sandbox, sessions_dir, cwd, int(now) - 10, out)
        assert r.returncode != 0, "截断会话不得当作有效 findings"
        assert not out.exists()

    def test_13_ignores_sessions_older_than_window(self, tmp_path):
        """mtime 早于本次 exec 启动时刻的历史会话不得被采用（同目录多 run 隔离）。"""
        sandbox = self._sandbox(tmp_path)
        sessions_dir = sandbox.ws / "sessions"
        cwd = "/tmp/x/head-src"
        now = time.time()
        write_session(sessions_dir, cwd, FINDINGS, mtime=now - 1000)
        out = sandbox.ws / "recovered.json"
        r = run_helper(sandbox, sessions_dir, cwd, int(now) - 10, out)
        assert r.returncode != 0, "时间窗外的会话不得恢复"
        assert not out.exists()

    def test_14_requires_run_marker_in_session(self, tmp_path):
        """不含本 run prompt 标记的会话（其他 run / 手工会话）不得被采用。"""
        sandbox = self._sandbox(tmp_path)
        sessions_dir = sandbox.ws / "sessions"
        cwd = "/tmp/x/head-src"
        now = time.time()
        write_session(sessions_dir, cwd, FINDINGS, marker=None, mtime=now)
        out = sandbox.ws / "recovered.json"
        r = run_helper(sandbox, sessions_dir, cwd, int(now) - 10, out)
        assert r.returncode != 0, "无标记会话不得恢复"
        assert not out.exists()

    def test_15_missing_sessions_dir_fails(self, tmp_path):
        sandbox = self._sandbox(tmp_path)
        out = sandbox.ws / "recovered.json"
        r = run_helper(
            sandbox, sandbox.ws / "nonexistent", "/tmp/x/head-src", int(time.time()), out
        )
        assert r.returncode != 0

    def test_16_warning_tags_source_session(self, tmp_path):
        """成功恢复必须打 ::warning 且标注来源会话文件（expectedBehavior #2）。"""
        sandbox = self._sandbox(tmp_path)
        sessions_dir = sandbox.ws / "sessions"
        cwd = "/tmp/x/head-src"
        now = time.time()
        p = write_session(sessions_dir, cwd, FINDINGS, mtime=now, session_id="src-session")
        out = sandbox.ws / "recovered.json"
        r = run_helper(sandbox, sessions_dir, cwd, int(now) - 10, out)
        assert r.returncode == 0
        assert "::warning" in r.stdout
        assert p.name in r.stdout, "warning 必须标注来源会话文件"


# ════════════════════════════════════════════════════════════════════════
# Part C: 脚本契约（文本级，防回归回退）
# ════════════════════════════════════════════════════════════════════════


class TestScriptContract:
    def test_21_retry_gated_on_137_and_empty_stdout(self):
        content = ENGINE_RUN_SHARD.read_text()
        assert "-eq 137" in content, "重试必须以 exit 137 为门"
        assert content.count("droid exec \\") == 2, "恰好两处 droid exec 调用（首次 + 单次重试）"

    def test_22_recovery_before_fail_closed(self):
        content = ENGINE_RUN_SHARD.read_text()
        assert "recover_shard_findings.sh" in content, "必须引用会话恢复助手"
        rec_idx = content.index("RECOVER_HELPER")
        assert rec_idx > 0
        # fail-closed 的最终出口仍在（语义保留）
        assert content.count("fail-closed") >= 2

    def test_23_prompt_embeds_run_unique_marker(self):
        content = ENGINE_RUN_SHARD.read_text()
        assert "droid-review-shard-marker:" in content, (
            "prompt 必须嵌入 run 唯一标记（会话候选防串扰）"
        )
        assert "PROMPT_EOF" in content

    def test_24_helper_exists_in_engine_dir(self):
        assert ENGINE_RECOVER_HELPER.exists(), "engine 目录必须有 recover_shard_findings.sh"

    # 注：memory-core scripts/droid_review/run_shard.sh 消费副本不在本测试范围——
    # 该副本由 gate-droid-review（thin caller 切换）收编，切换后引擎副本即唯一活体。
