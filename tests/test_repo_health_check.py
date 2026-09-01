"""Contract tests for repo_health_check.sh"""

import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "repo_health_check.sh"


@pytest.mark.business_policy
def test_repo_health_check_script_exists() -> None:
    """repo_health_check.sh must exist in scripts/"""
    assert SCRIPT.exists(), "scripts/repo_health_check.sh must exist"


@pytest.mark.business_policy
def test_repo_health_check_passes_on_clean_repo() -> None:
    """repo_health_check.sh must pass on a clean repo"""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        cwd=REPO_ROOT,
        env=_script_env(),
    )
    assert result.returncode == 0, f"Repo health check failed: {result.stderr.decode()}"


@pytest.mark.business_policy
def test_repo_health_check_checks_uvlock_root_version_alignment() -> None:
    """Check 1b must fail on uv.lock root package version drift (INFRA-712).

    release-please Release PR 只 bump pyproject 不 relock（PR #136 实证），
    0.7.2 漂移即由此产生（PR #163 补救）。本契约在临时 git 仓库里构造
    uv.lock 根包版本回退，断言脚本以非零退出并报告漂移——锁定守护
    有效性，防止后续编辑静默移除该检查。
    """
    if not shutil.which("git"):
        pytest.skip("git not available")

    with tempfile_git_repo() as repo:
        # 构造漂移：uv.lock 根包版本回退一个小版本
        lock_path = repo / "uv.lock"
        original = lock_path.read_text(encoding="utf-8")
        pyproject_version = read_pyproject_version(repo)
        drifted = original.replace(
            f'name = "{read_pyproject_name(repo)}"\nversion = "{pyproject_version}"',
            f'name = "{read_pyproject_name(repo)}"\nversion = "0.0.1"',
        )
        assert drifted != original, "test fixture failed to construct drift"
        lock_path.write_text(drifted, encoding="utf-8")

        result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            cwd=repo,
            env=_script_env(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, (
            f"repo_health_check.sh must fail on uv.lock root version drift; got 0. output:\n{combined}"
        )
        assert "uv.lock" in combined and "mismatch" in combined, (
            f"failure output must name the uv.lock drift:\n{combined}"
        )


@pytest.mark.business_policy
def test_repo_health_check_uvlock_check_uses_pyproject_name_not_hardcoded() -> None:
    """Check 1b root package lookup must key off pyproject [project].name.

    硬编码包名的检查在包重命名后失效（找旧名 → not found → 误报或漏报）。
    本契约锁定脚本正文包含动态名字来源（tomllib 解析 pyproject），
    防止后续编辑退化为硬编码 "infra-core" 字面匹配。
    """
    script_text = SCRIPT.read_text(encoding="utf-8")
    # 动态名字来源：python 内联块读 pyproject 的 [project].name
    assert "tomllib" in script_text, "must parse uv.lock/pyproject with tomllib"
    assert "project['name']" in script_text, (
        "root package name must come from pyproject, not hardcoded"
    )


@pytest.mark.business_policy
def test_release_please_workflow_relocks_uvlock_on_release_pr() -> None:
    """release-please.yml must carry the INFRA-712 relock step.

    Release PR 只 bump pyproject 不 relock 是漂移源头（PR #136 实证）。
    本契约锁定 release-please.yml 含 relock 步骤的关键要素，防后续
    编辑静默删除使漂移复发。
    """
    import yaml

    wf_path = REPO_ROOT / ".github" / "workflows" / "release-please.yml"
    wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    job = wf["jobs"]["release-please"]
    steps = job["steps"]

    # action 需要 id 才能暴露 release_branch 输出供 relock 步骤消费
    action_steps = [s for s in steps if "release-please-action" in str(s.get("uses", ""))]
    assert action_steps, "release-please-action step must exist"
    assert action_steps[0].get("id") == "release", "action step needs id=release for outputs"

    relock_steps = [s for s in steps if "relock" in s.get("name", "").lower()]
    assert relock_steps, "relock step (INFRA-712) must exist in release-please.yml"
    run = relock_steps[0].get("run", "")
    for fragment in (
        "uv lock",  # 实际 relock 命令
        "steps.release.outputs.release_branch",  # 只在 Release PR 存在时执行
        "git push",  # 回推到 Release PR 分支
    ):
        assert fragment in run, f"relock step must contain {fragment!r}; got:\n{run}"


@pytest.mark.business_policy
def test_release_please_relock_degrades_gracefully_without_uv() -> None:
    """Relock step must not break releases when uv is unavailable.

    发版不因 relock 失败中断（设计裁定）：uv 缺失时 warning + exit 0，
    漂移由 repo_health_check.sh Check 1b 在 CI 门禁兜底。锁定降级
    语义，防止后续编辑改成硬失败卡死发版链路。
    """
    import yaml

    wf_path = REPO_ROOT / ".github" / "workflows" / "release-please.yml"
    wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    steps = wf["jobs"]["release-please"]["steps"]
    relock_steps = [s for s in steps if "relock" in s.get("name", "").lower()]
    assert relock_steps, "relock step must exist"
    run = relock_steps[0].get("run", "")
    assert "command -v uv" in run, "must probe uv availability first"
    assert "::warning::" in run, "uv missing must emit a warning annotation"
    # 降级语义：探测失败分支 exit 0（软跳过），不能 exit 1 硬失败
    probe_block = run.split("command -v uv", 1)[1]
    early_exit = probe_block.split("fi", 1)[0]
    assert "exit 0" in early_exit, "uv-missing branch must exit 0 (degrade, not fail)"


# ─── helpers ───


def _script_env() -> dict[str, str] | None:
    """Ensure subprocess `python3` has tomllib (>= 3.11).

    本机默认 python3 可能是 3.9（无 tomllib）；仓库 requires-python 是
    ==3.12.*，CI runner 预装 3.12 无此问题。本地运行测试时若当前解释器
    有 tomllib 而 PATH 上的 python3 没有，把当前解释器目录前置到子进程
    PATH，保证被测脚本的 `python3` 与测试解释器同源。
    """
    import os
    import sys

    probe = subprocess.run(["python3", "-c", "import tomllib"], capture_output=True)
    if probe.returncode == 0:
        return None
    if sys.version_info < (3, 11):
        return None  # 当前解释器也没有 tomllib，无法补救，按原样运行
    return {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}


def read_pyproject_version(repo: Path) -> str:
    with (repo / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def read_pyproject_name(repo: Path) -> str:
    with (repo / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["name"])


@contextmanager
def tempfile_git_repo() -> Iterator[Path]:
    """Materialize a temp git repo mirroring REPO_ROOT's checked-in files.

    repo_health_check.sh 顶部 `git rev-parse --show-toplevel && cd` 会把
    工作目录钉到真实仓库根，无法在子目录内构造漂移——必须把脚本连同
    pyproject.toml/uv.lock 复制进临时 git 仓库再运行。
    """
    with tempfile.TemporaryDirectory(prefix="infra712-health-") as name:
        repo = Path(name)
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        for rel in ("pyproject.toml", "uv.lock", "scripts/repo_health_check.sh"):
            src = REPO_ROOT / rel
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        # .release-please-manifest.json 若缺失会让 Check 1 先报错，淹没了被测
        # 的 Check 1b 输出；复制以保持单一失败源
        manifest = REPO_ROOT / ".release-please-manifest.json"
        if manifest.exists():
            shutil.copy2(manifest, repo / ".release-please-manifest.json")
        yield repo
