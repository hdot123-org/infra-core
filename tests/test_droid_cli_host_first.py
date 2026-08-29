"""droid-review 链路 Factory CLI 宿主优先契约测试（2026-08-29 factory-cli-host-first-preinstall）。

回归保护：droid-review 分片流水线的 droid CLI 安装必须宿主优先——
PATH 命中且版本 ≥0.200 直接使用（零外网下载），仅宿主缺失/过旧时
才 fallback ``curl app.factory.ai/cli`` 下载并打 ::warning。

背景：``curl app.factory.ai/cli`` 是 node-00 出口拓扑下最后一条非镜像
下载路径——PR #52 review-shard 被 runner shutdown 杀死在下载中、
PR #61 首轮 droid-review 同因红（rerun 自愈）。修复照抄 actionlint
host-first 模式（PR #53，TestActionlintHostFirst）：ce-01 五台 pve
runner 预装 /usr/local/bin/droid（Layer 1 离线化），CI 日志宿主优先
命中，正常全绿 run 零 curl 到 app.factory.ai。

契约覆盖两个载体（同 BYOM tailnet 契约 test_droid_review_byom_tailnet
的双载体模式）：
- 自仓 droid-review.yml（infra-core PR 的 droid-review 生产形态）
- reusable workflow droid-review-shards.yml（memory-core 等 thin
  caller 的分片流水线载体）
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent

# 宿主优先契约覆盖两个载体：自仓 droid-review.yml + reusable workflow
# droid-review-shards.yml（M4 起 memory-core 等 thin caller 的分片流水线走后者）
WORKFLOW_PATHS = [
    REPO_ROOT / ".github/workflows/droid-review.yml",
    REPO_ROOT / ".github/workflows/droid-review-shards.yml",
]

INSTALL_STEP_NAME = "Install Droid CLI"
# 版本下限：宿主实装 0.206.0（本机）/ 0.208.1（CI 现装，run 33249966263），
# 下限取 0.200 —— 已知可用版本全部通过，更旧的宿主二进制走 fallback 下载。
VERSION_FLOOR_MINOR = 200


def _get_install_step(workflow_path: Path) -> dict[str, Any]:
    """定位 review-shard job 的 Install Droid CLI step。"""
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    shard_job = data["jobs"]["review-shard"]
    for step in shard_job.get("steps", []):
        if step.get("name") == INSTALL_STEP_NAME:
            return step
    pytest.fail(f"{workflow_path.name}: review-shard job must have a {INSTALL_STEP_NAME!r} step")


@pytest.fixture(params=WORKFLOW_PATHS, ids=[p.name for p in WORKFLOW_PATHS])
def install_script(request: pytest.FixtureRequest) -> str:
    step = _get_install_step(request.param)
    return str(step["run"])


class TestDroidCliHostFirst:
    """Factory CLI 安装宿主优先契约（参照 TestActionlintHostFirst 模式）。"""

    def test_host_binary_probe_present(self, install_script: str) -> None:
        """安装步必须先探测宿主二进制（PATH 优先分支）。"""
        assert "command -v droid" in install_script, "缺少宿主二进制探测（PATH 优先分支）"

    def test_host_version_gate(self, install_script: str) -> None:
        """宿主版本必须 ≥0.200 才直接使用（防过旧宿主二进制误用）。"""
        assert "-ge 200" in install_script, "缺少宿主版本 ≥0.200 门限判断"

    def test_fallback_missing_warns(self, install_script: str) -> None:
        """宿主缺失时 fallback 下载必须打 ::warning（异常态要显式暴露）。"""
        assert "::warning::droid not found on host" in install_script, (
            "宿主缺失 fallback 分支缺少 ::warning"
        )

    def test_fallback_stale_warns(self, install_script: str) -> None:
        """宿主版本过旧 fallback 也必须打 ::warning。"""
        assert "::warning::host droid" in install_script, "宿主过旧 fallback 分支缺少 ::warning"

    def test_download_only_after_host_probe(self, install_script: str) -> None:
        """curl 下载只允许存在于宿主探测之后（禁止恢复每 run 无条件首下载）。"""
        assert "app.factory.ai/cli" in install_script, (
            "fallback 下载路径必须保留（GitHub-hosted 兼容）"
        )
        probe_at = install_script.index("command -v droid")
        download_at = install_script.index("app.factory.ai/cli")
        assert probe_at < download_at, "下载路径出现在宿主探测之前（退化为无条件下载）"

    def test_curl_retry_resilience_preserved(self, install_script: str) -> None:
        """fallback curl 保留 --retry 韧性（出口抖动只应单次红，rerun 可自愈）。"""
        assert "--retry" in install_script, "fallback curl 缺少 --retry"
        assert "--retry-all-errors" in install_script, "fallback curl 缺少 --retry-all-errors"

    def test_fallback_wires_local_bin_path(self, install_script: str) -> None:
        """fallback 分支保留 ~/.local/bin → GITHUB_PATH 接线（后续步骤解析 droid）。"""
        assert '"$HOME/.local/bin" >> "$GITHUB_PATH"' in install_script, (
            "fallback 分支缺少 GITHUB_PATH 接线（后续步骤将解析不到 droid）"
        )

    def test_effective_version_logged(self, install_script: str) -> None:
        """宿主/fallback 两条路径都必须输出生效版本（CI 日志可审计宿主优先命中）。"""
        assert "droid --version" in install_script, "缺少生效版本输出（宿主优先命中不可审计）"
