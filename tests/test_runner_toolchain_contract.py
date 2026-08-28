"""Runner 工具链契约测试（runner-host-toolchain-pin-cache）

验证宿主机工具二进制版本锁定和缓存策略的契约一致性。
Layer 1: 工具二进制版本锁定（runner-tools.toml 单一事实源）
Layer 2: 缓存目录锁定（UV_CACHE_DIR/PIP_CACHE_DIR）
护栏铁律：只锁工具二进制，被测包的 per-run venv 独立安装不动
"""

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.business_policy]

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _load_runner_tools() -> dict:
    """加载 runner-tools.toml 并返回解析后的字典"""
    content = _read("runner-tools.toml")
    return tomllib.loads(content)


class TestRunnerToolsManifest:
    """测试 runner-tools.toml 清单文件的完整性"""

    def test_runner_tools_toml_exists(self):
        """runner-tools.toml 必须存在"""
        assert (REPO_ROOT / "runner-tools.toml").exists()

    def test_runner_tools_toml_has_tools_section(self):
        """必须包含 [tools] 段，列出所有预装工具"""
        data = _load_runner_tools()
        assert "tools" in data
        tools = data["tools"]

        # 必须包含的 6 个核心工具
        required_tools = {"uv", "ruff", "mypy", "actionlint", "shellcheck", "jq"}
        assert set(tools.keys()) == required_tools, (
            f"runner-tools.toml [tools] 必须包含 {required_tools}，实际包含 {set(tools.keys())}"
        )

    def test_runner_tools_toml_has_cache_section(self):
        """必须包含 [cache] 段，指定缓存目录"""
        data = _load_runner_tools()
        assert "cache" in data
        cache = data["cache"]

        # 必须包含的缓存目录配置
        assert "uv_cache_dir" in cache
        assert "pip_cache_dir" in cache

        # 缓存目录必须是绝对路径
        assert cache["uv_cache_dir"].startswith("/"), "uv_cache_dir 必须是绝对路径"
        assert cache["pip_cache_dir"].startswith("/"), "pip_cache_dir 必须是绝对路径"

    def test_runner_tools_toml_has_runner_section(self):
        """必须包含 [runner] 段，指定 runner 标签"""
        data = _load_runner_tools()
        assert "runner" in data
        runner = data["runner"]

        assert "labels" in runner
        assert isinstance(runner["labels"], list)
        # 必须包含 self-hosted 和 pve-linux
        assert "self-hosted" in runner["labels"]
        assert "pve-linux" in runner["labels"]

    def test_tool_versions_are_pinned(self):
        """所有工具版本必须是精确版本（不含 >= 或 ~）"""
        data = _load_runner_tools()
        tools = data["tools"]

        for tool, version in tools.items():
            assert isinstance(version, str), f"{tool} 的版本必须是字符串"
            # 不允许范围操作符
            assert ">=" not in version, f"{tool} 版本 {version} 包含 '>='，必须精确锁定"
            assert "~" not in version, f"{tool} 版本 {version} 包含 '~'，必须精确锁定"
            assert "^" not in version, f"{tool} 版本 {version} 包含 '^'，必须精确锁定"


class TestCIWorkflowHostToolPriority:
    """测试 CI workflow 实现了宿主工具优先逻辑"""

    def test_actionlint_job_host_priority(self):
        """actionlint job 必须优先使用宿主预装，失败时才下载"""
        content = _read(".github/workflows/ci.yml")

        # 必须包含宿主优先检查
        assert "command -v actionlint" in content, "actionlint job 必须检查宿主是否预装"

        # 必须包含 fallback 下载逻辑
        assert "raw.githubusercontent.com/rhysd/actionlint" in content, (
            "actionlint job 必须保留 fallback 下载路径"
        )

        # 必须包含警告日志（宿主未预装时）
        assert "::warning::actionlint not found on host" in content, (
            "actionlint job 必须在宿主未预装时输出警告"
        )

    def test_shellcheck_job_host_priority(self):
        """shellcheck job 必须优先使用宿主预装，失败时才下载"""
        content = _read(".github/workflows/ci.yml")

        # 必须包含宿主优先检查
        assert "command -v shellcheck" in content, "shellcheck job 必须检查宿主是否预装"

        # 必须包含 fallback 下载逻辑
        assert "github.com/koalaman/shellcheck/releases" in content, (
            "shellcheck job 必须保留 fallback 下载路径"
        )

        # 必须包含警告日志（宿主未预装时）
        assert "::warning::shellcheck not found on host" in content, (
            "shellcheck job 必须在宿主未预装时输出警告"
        )

    def test_actionlint_no_unconditional_download(self):
        """actionlint 不得无条件下载（必须走宿主优先逻辑）"""
        content = _read(".github/workflows/ci.yml")

        # 不应该存在无条件下载的 bash <(curl ...) 模式
        # 注意：这个模式在宿主优先逻辑的 else 分支是允许的
        # 所以我们检查的是：不能在没有 command -v 检查的情况下直接下载

        # 找到 actionlint job 的定义
        actionlint_job_match = re.search(
            r"^  actionlint:.*?(?=^  \w|\Z)", content, re.MULTILINE | re.DOTALL
        )
        assert actionlint_job_match, "未找到 actionlint job 定义"

        job_content = actionlint_job_match.group(0)

        # 必须包含宿主检查
        assert "command -v actionlint" in job_content, "actionlint job 必须先检查宿主预装"


class TestSetupVenvCacheIntegration:
    """测试 setup-venv composite action 的缓存集成"""

    def test_setup_venv_detects_host_tools(self):
        """setup-venv 必须探测宿主工具并记录版本"""
        content = _read(".github/actions/setup-venv/action.yml")

        # 必须包含工具探测逻辑
        assert "for tool in uv ruff mypy actionlint shellcheck jq" in content, (
            "setup-venv 必须探测 6 个核心工具"
        )

        # 必须输出工具版本信息
        assert "$tool --version" in content, "setup-venv 必须输出工具版本"

    def test_setup_venv_exports_cache_dirs(self):
        """setup-venv 必须导出缓存目录环境变量"""
        content = _read(".github/actions/setup-venv/action.yml")

        # 必须设置 UV_CACHE_DIR
        assert (
            'UV_CACHE_DIR="/var/cache/uv"' in content or "UV_CACHE_DIR=/var/cache/uv" in content
        ), "setup-venv 必须设置 UV_CACHE_DIR=/var/cache/uv"

        # 必须设置 PIP_CACHE_DIR
        assert (
            'PIP_CACHE_DIR="/var/cache/pip"' in content or "PIP_CACHE_DIR=/var/cache/pip" in content
        ), "setup-venv 必须设置 PIP_CACHE_DIR=/var/cache/pip"

        # 必须导出到 GITHUB_ENV
        assert (
            'UV_CACHE_DIR="$UV_CACHE_DIR" >> "$GITHUB_ENV"' in content
            or 'echo "UV_CACHE_DIR=' in content
        ), "setup-venv 必须导出 UV_CACHE_DIR 到 GITHUB_ENV"

    def test_setup_venv_preserves_per_run_venv_isolation(self):
        """setup-venv 必须保持 per-run venv 隔离（护栏铁律）"""
        content = _read(".github/actions/setup-venv/action.yml")

        # 必须使用 RUN_ID 和 RUN_ATTEMPT 创建唯一 venv 路径
        assert "venv-${RUN_ID}-${RUN_ATTEMPT}" in content, (
            "setup-venv 必须按 run_id+run_attempt 创建唯一 venv 路径"
        )

        # 必须前置 venv 到 PATH
        assert 'echo "$VENV/bin" >> "$GITHUB_PATH"' in content, (
            "setup-venv 必须将 venv/bin 前置到 PATH"
        )

        # 必须设置 VIRTUAL_ENV
        assert 'echo "VIRTUAL_ENV=$VENV"' in content, "setup-venv 必须设置 VIRTUAL_ENV 环境变量"

    def test_setup_venv_has_getpip_fallback(self):
        """setup-venv 必须在 ensurepip 缺失时回退到 get-pip.py"""
        content = _read(".github/actions/setup-venv/action.yml")

        # 必须包含 get-pip.py 回退逻辑
        assert "get-pip.py" in content, "setup-venv 必须包含 get-pip.py 回退逻辑"

        # 必须包含警告日志
        assert (
            "::warning::python3 -m venv failed" in content
            or "::warning::python3 -m venv failed (ensurepip missing?)" in content
        ), "setup-venv 必须在 venv 创建失败时输出警告"


class TestRunnerToolchainVersionConsistency:
    """测试 runner-tools.toml 与 CI workflow 的版本一致性"""

    def test_actionlint_version_matches(self):
        """runner-tools.toml 的 actionlint 版本必须与 CI workflow 的 fallback 版本一致"""
        data = _load_runner_tools()
        actionlint_version = data["tools"]["actionlint"]

        content = _read(".github/workflows/ci.yml")

        # 提取 CI workflow 中 actionlint 的版本号
        # 格式：v1.7.12 或 1.7.12
        version_pattern = r"v?(\d+\.\d+\.\d+)"
        matches = re.findall(
            r"raw\.githubusercontent\.com/rhysd/actionlint/" + version_pattern, content
        )

        assert len(matches) > 0, "CI workflow 未找到 actionlint 下载 URL"
        ci_version = matches[0]

        assert ci_version == actionlint_version, (
            f"runner-tools.toml actionlint={actionlint_version}，"
            f"CI workflow fallback={ci_version}，版本不一致"
        )

    def test_shellcheck_version_matches(self):
        """runner-tools.toml 的 shellcheck 版本必须与 CI workflow 的 fallback 版本一致"""
        data = _load_runner_tools()
        shellcheck_version = data["tools"]["shellcheck"]

        content = _read(".github/workflows/ci.yml")

        # 提取 CI workflow 中 shellcheck 的版本号
        # 格式：v0.10.0 或 0.10.0
        version_pattern = r"v?(\d+\.\d+\.\d+)"
        matches = re.findall(
            r"github\.com/koalaman/shellcheck/releases/download/" + version_pattern, content
        )

        assert len(matches) > 0, "CI workflow 未找到 shellcheck 下载 URL"
        ci_version = matches[0]

        assert ci_version == shellcheck_version, (
            f"runner-tools.toml shellcheck={shellcheck_version}，"
            f"CI workflow fallback={ci_version}，版本不一致"
        )


class TestLayer1Layer2Guardrails:
    """测试 Layer 1+2 护栏铁律"""

    def test_per_run_venv_not_locked(self):
        """护栏铁律：被测包的 per-run venv 不能锁定到宿主"""
        content = _read(".github/actions/setup-venv/action.yml")

        # setup-venv 不能将宿主工具安装到 venv 内
        # 检查是否存在 pip install ruff/mypy/actionlint 等命令
        # 注意：setup-venv 只安装被测包依赖，不安装工具

        # 提取 Install deps 部分
        install_match = re.search(r"name: Install deps.*?(?=\n    - name:|\Z)", content, re.DOTALL)

        if install_match:
            install_block = install_match.group(0)

            # 不应该安装工具（只安装被测包依赖）
            forbidden_tools = ["ruff", "mypy", "actionlint", "shellcheck"]
            for tool in forbidden_tools:
                # 检查是否有 pip install <tool> 的模式
                # 注意：pytest 和 pytest-cov 等测试依赖是允许的
                if re.search(rf"pip install.*\b{tool}\b", install_block):
                    pytest.fail(
                        f"setup-venv 的 Install deps 块安装了 {tool}，"
                        f"违反护栏铁律：工具应使用宿主预装，不安装到 venv"
                    )

    def test_cache_dirs_are_shared(self):
        """缓存目录必须是 runner 全局共享的"""
        data = _load_runner_tools()
        cache = data["cache"]

        # 缓存目录必须是系统级路径（/var/cache/...）
        # 不能是用户级路径（~/.cache/... 或 $HOME/.cache/...）
        for key in ["uv_cache_dir", "pip_cache_dir"]:
            path = cache[key]
            assert not path.startswith("~"), (
                f"{key}={path} 是用户级路径，必须是 runner 全局共享的 /var/cache/..."
            )
            assert not path.startswith("$HOME"), (
                f"{key}={path} 是用户级路径，必须是 runner 全局共享的 /var/cache/..."
            )
            assert path.startswith("/var/cache/"), (
                f"{key}={path} 必须是 /var/cache/... 路径，确保 runner 全局共享"
            )
