"""Runner 工具链契约测试（runner-host-toolchain-pin-cache，抢救性重构自 PR #37 / INFRA-590）

验证宿主机工具二进制版本锁定和缓存策略的契约一致性。
Layer 1: 工具二进制版本锁定（runner-tools.toml 单一事实源 = 宿主预装实测版本）
Layer 2: 缓存目录锁定（UV_CACHE_DIR/PIP_CACHE_DIR=/var/cache/{uv,pip}）
护栏铁律：只锁工具二进制，被测包的 per-run venv 独立安装不动

INFRA-590 专项回归护栏：setup-venv 的「Install dependencies」步骤不可缺失
——被取代的 PR #37 首版重构 setup-venv 时误删该步骤且无替代，导致 CI 全红。
"""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent

ACTION_YAML = REPO_ROOT / ".github" / "actions" / "setup-venv" / "action.yml"
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_TOOLS = {"uv", "ruff", "mypy", "actionlint", "shellcheck", "jq"}


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _load_runner_tools() -> dict:
    """加载 runner-tools.toml 并返回解析后的字典"""
    return tomllib.loads(_read("runner-tools.toml"))


def _load_action_steps() -> list[dict]:
    return yaml.safe_load(ACTION_YAML.read_text(encoding="utf-8"))["runs"]["steps"]


def _job_step_script(rel_path: str, job_key: str, step_name: str) -> str:
    """从 workflow YAML 中按 job + 步骤名截取 run 脚本文本。

    #61 容量收敛（19→10 job bundle 化）后，shellcheck/actionlint 不再是 ci.yml
    独立 job，而是 lint-bundle 内的步骤——宿主优先契约按步骤粒度钉住。
    """
    doc = yaml.safe_load(_read(rel_path))
    steps = (doc.get("jobs") or {}).get(job_key, {}).get("steps") or []
    scripts = [s["run"] for s in steps if s.get("name") == step_name and "run" in s]
    assert scripts, f"{rel_path} 的 job {job_key} 未找到步骤：{step_name}"
    return scripts[0]


class TestRunnerToolsManifest:
    """测试 runner-tools.toml 清单文件的完整性"""

    def test_runner_tools_toml_exists(self):
        """runner-tools.toml 必须存在"""
        assert (REPO_ROOT / "runner-tools.toml").exists()

    def test_tools_section_lists_exactly_six_core_tools(self):
        """[tools] 必须恰好列出 6 个核心工具（uv/ruff/mypy/actionlint/shellcheck/jq）"""
        tools = _load_runner_tools()["tools"]
        assert set(tools.keys()) == REQUIRED_TOOLS, (
            f"[tools] 必须包含 {REQUIRED_TOOLS}，实际 {set(tools.keys())}"
        )

    def test_tool_versions_are_exact_pins(self):
        """所有工具版本必须是精确版本字符串（禁止范围/通配操作符）"""
        for tool, version in _load_runner_tools()["tools"].items():
            assert isinstance(version, str) and version, f"{tool} 版本必须是非空字符串"
            for op in (">=", "<=", "~", "^", "*"):
                assert op not in version, f"{tool} 版本 {version} 含 '{op}'，必须精确锁定"

    def test_cache_section_locks_runner_global_dirs(self):
        """[cache] 必须锁定 runner 全局共享缓存目录（/var/cache/...，非用户级路径）"""
        cache = _load_runner_tools()["cache"]
        assert cache["uv_cache_dir"] == "/var/cache/uv"
        assert cache["pip_cache_dir"] == "/var/cache/pip"

    def test_runner_labels_declare_selfhosted_pve(self):
        """[runner] labels 必须声明 self-hosted + pve-linux（runs-on 选择器契约）"""
        labels = _load_runner_tools()["runner"]["labels"]
        assert isinstance(labels, list)
        assert "self-hosted" in labels
        assert "pve-linux" in labels

    def test_ci_fallback_keys_subset_of_tools_with_exact_pins(self):
        """[ci_fallback] 键必须是 [tools] 子集且版本精确（回退下载版本与清单钉住）"""
        data = _load_runner_tools()
        fallback = data["ci_fallback"]
        assert set(fallback.keys()) <= set(data["tools"].keys())
        for tool, version in fallback.items():
            assert isinstance(version, str) and version, f"ci_fallback.{tool} 版本必须非空"
            assert re.fullmatch(r"\d+\.\d+(\.\d+)?", version), (
                f"ci_fallback.{tool}={version} 必须是精确版本号"
            )


class TestSetupVenvLayer12:
    """测试 setup-venv composite action 的 Layer 1+2 集成"""

    def test_host_detection_covers_manifest_tools(self):
        """探测循环必须覆盖 runner-tools.toml [tools] 的全部工具（同构不遗漏）"""
        content = ACTION_YAML.read_text(encoding="utf-8")
        match = re.search(r"for tool in ([a-z ]+); do", content)
        assert match, "setup-venv 未找到宿主工具探测 for 循环"
        detected = set(match.group(1).split())
        manifest = set(_load_runner_tools()["tools"].keys())
        assert detected == manifest, f"探测集合 {detected} 与清单 {manifest} 不一致"

    def test_exports_shared_cache_dirs_matching_manifest(self):
        """必须导出与清单 [cache] 一致的 UV_CACHE_DIR/PIP_CACHE_DIR 到 GITHUB_ENV"""
        content = ACTION_YAML.read_text(encoding="utf-8")
        cache = _load_runner_tools()["cache"]
        assert f'export UV_CACHE_DIR="{cache["uv_cache_dir"]}"' in content
        assert f'export PIP_CACHE_DIR="{cache["pip_cache_dir"]}"' in content
        assert 'echo "UV_CACHE_DIR=$UV_CACHE_DIR" >> "$GITHUB_ENV"' in content
        assert 'echo "PIP_CACHE_DIR=$PIP_CACHE_DIR" >> "$GITHUB_ENV"' in content

    def test_per_run_venv_isolation_preserved(self):
        """护栏铁律：venv 按 run_id+run_attempt 唯一路径，前置 PATH 并导出 VIRTUAL_ENV/VENV_PATH"""
        content = ACTION_YAML.read_text(encoding="utf-8")
        assert "venv-${RUN_ID}-${RUN_ATTEMPT}" in content, "必须按 run_id+attempt 建唯一 venv"
        assert 'echo "$VENV/bin" >> "$GITHUB_PATH"' in content
        assert 'echo "VIRTUAL_ENV=$VENV" >> "$GITHUB_ENV"' in content
        assert 'echo "VENV_PATH=$VENV" >> "$GITHUB_ENV"' in content

    def test_getpip_fallback_present(self):
        """ensurepip 缺失时必须回退 --without-pip + get-pip.py 引导"""
        content = ACTION_YAML.read_text(encoding="utf-8")
        assert "--without-pip" in content
        assert "get-pip.py" in content
        assert "::warning::python3 -m venv failed" in content

    def test_venv_pip_upgraded_after_creation(self):
        """venv 创建后必须升级 pip：ensurepip 自带 pip 24.0 的 PYSEC 公告会让
        pip-audit（扫 venv 自身）红掉 advisory-bundle（2026-08-29 实证回归）"""
        content = ACTION_YAML.read_text(encoding="utf-8")
        assert "pip install --upgrade pip" in content, (
            "setup-venv 必须在 venv 创建后升级 pip，否则 advisory-bundle 必红"
        )

    def test_install_dependencies_step_preserved(self):
        """INFRA-590 回归护栏：「Install dependencies」步骤必须存在且安装 -e ".[dev]\""""
        steps = _load_action_steps()
        install_steps = [s for s in steps if s.get("name") == "Install dependencies"]
        assert len(install_steps) == 1, "setup-venv 必须保留且仅保留一个 Install dependencies 步骤"
        install = install_steps[0]
        assert install is steps[-1], "Install dependencies 必须是 composite 的最后一个步骤"
        assert 'pip install -e ".[dev]"' in install["run"], "必须安装 -e .[dev]（依赖不可缺失）"

    def test_install_step_does_not_install_host_tools(self):
        """护栏铁律：Install dependencies 块不得把宿主工具装进 venv"""
        install = next(s for s in _load_action_steps() if s.get("name") == "Install dependencies")
        for tool in ("ruff", "mypy", "actionlint", "shellcheck"):
            assert not re.search(rf"pip install.*\b{tool}\b", install["run"]), (
                f"Install dependencies 不得安装宿主工具 {tool}（应走 PATH 优先的宿主预装）"
            )


class TestCIWorkflowHostFirst:
    """测试 ci.yml 的宿主工具优先消费逻辑（#61 bundle 化后位于 lint-bundle 步骤）"""

    def test_actionlint_step_keeps_host_first_pattern(self):
        """actionlint 步骤（#53 已落地）必须保留宿主优先 + 回退下载双分支"""
        script = _job_step_script(".github/workflows/ci.yml", "lint-bundle", "Run actionlint")
        assert "command -v actionlint" in script
        assert "raw.githubusercontent.com/rhysd/actionlint" in script
        assert "::warning::actionlint not found on host" in script

    def test_shellcheck_step_host_first(self):
        """shellcheck 步骤必须宿主优先：命中即用，缺失才回退下载并打警告"""
        script = _job_step_script(
            ".github/workflows/ci.yml", "lint-bundle", "Detect host shellcheck (Layer 1)"
        )
        assert "command -v shellcheck" in script
        assert "github.com/koalaman/shellcheck/releases" in script
        assert "::warning::shellcheck not found on host" in script

    def test_shellcheck_fallback_version_matches_manifest(self):
        """shellcheck 回退下载版本必须与 runner-tools.toml [ci_fallback] 一致"""
        script = _job_step_script(
            ".github/workflows/ci.yml", "lint-bundle", "Detect host shellcheck (Layer 1)"
        )
        matches = re.findall(
            r"github\.com/koalaman/shellcheck/releases/download/v(\d+\.\d+\.\d+)/", script
        )
        assert matches, "ci.yml shellcheck 步骤未找到回退下载 URL"
        assert set(matches) == {_load_runner_tools()["ci_fallback"]["shellcheck"]}

    def test_actionlint_fallback_version_matches_manifest(self):
        """actionlint 回退下载版本必须与 runner-tools.toml [ci_fallback] 一致"""
        script = _job_step_script(".github/workflows/ci.yml", "lint-bundle", "Run actionlint")
        matches = re.findall(
            r"raw\.githubusercontent\.com/rhysd/actionlint/v(\d+\.\d+\.\d+)/", script
        )
        assert matches, "ci.yml actionlint 步骤未找到回退下载 URL"
        assert set(matches) == {_load_runner_tools()["ci_fallback"]["actionlint"]}
