"""Webhook-scripts manifest ownership contract tests（M5 shrink）.

webhook 生产同步的真源自本仓（architecture §7：webhook-scripts/MANIFEST.sh
迁 infra-core，memory-core 侧同名 manifest 已删除，过渡期不双 claim）。

本测试锁定三类不变量：
1. MANIFEST.sh 声明的每个受管文件在仓内真实存在（防 manifest 漂移）。
2. CROSS_DIR_MAPPINGS 源路径全部解析到引擎单源 src/infra_core/engine/
   （INFRA-679 收敛：不再维护 cross-dir/ 逐字节快照副本，也不允许
   memory-core 式 scripts/ 源路径或 cross-dir/ 快照复活）。
3. 引擎单源契约：cross-dir 快照目录不得复活，manifest 血缘注释记录
   INFRA-679 收敛决策。

生产同步验证（--check 对真实生产目录）不属于单测职责（依赖宿主环境），
由 mission 验证面（VAL-SHRINK-003/004）与 VAL-HARD-102 沙箱演练覆盖。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "webhook-scripts" / "MANIFEST.sh"


def _load_manifest_arrays() -> dict[str, list[str]]:
    """Source MANIFEST.sh in a bash subprocess and echo its arrays."""
    import subprocess

    script = (
        'source "' + str(MANIFEST_PATH) + '"\n'
        'for x in "${MANAGED_FILES[@]}"; do echo "MANAGED:$x"; done\n'
        'for x in "${MANAGED_LIB_FILES[@]}"; do echo "LIB:$x"; done\n'
        'for x in "${CROSS_DIR_MAPPINGS[@]}"; do echo "CROSS:$x"; done\n'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    arrays: dict[str, list[str]] = {"MANAGED": [], "LIB": [], "CROSS": []}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        kind, _, value = line.partition(":")
        if kind in arrays:
            arrays[kind].append(value)
    return arrays


class TestManagedFilesExist:
    """MANIFEST 声明的受管文件必须在仓内真实存在。"""

    def test_managed_files_exist_in_repo(self):
        arrays = _load_manifest_arrays()
        assert len(arrays["MANAGED"]) >= 10, "受管脚本清单不应缩水"
        for name in arrays["MANAGED"]:
            assert (REPO_ROOT / "webhook-scripts" / name).is_file(), f"missing: {name}"

    def test_managed_lib_files_exist_in_repo(self):
        arrays = _load_manifest_arrays()
        for name in arrays["LIB"]:
            assert (REPO_ROOT / "webhook-scripts" / name).is_file(), f"missing: {name}"

    def test_sync_script_exists(self):
        assert (REPO_ROOT / "webhook-scripts" / "sync-webhook-scripts.sh").is_file()


class TestCrossDirMappings:
    """CROSS_DIR 源路径必须解析到引擎单源（不双 claim、不悬空）。"""

    def test_cross_dir_sources_exist(self):
        arrays = _load_manifest_arrays()
        assert len(arrays["CROSS"]) == 4, "锚点依赖链四件套应完整声明"
        for mapping in arrays["CROSS"]:
            src, _, _dst = mapping.partition(":")
            assert (REPO_ROOT / src).is_file(), f"CROSS_DIR 源不存在: {src}"

    def test_cross_dir_sources_use_engine_single_source(self):
        """源路径必须收敛到引擎单源 src/infra_core/engine/（INFRA-679）。

        禁止两类回潮：
        - memory-core 式 scripts/ 源路径（VAL-SHRINK-005）；
        - cross-dir/ 逐字节快照副本（INFRA-679 已删除的双副本形态，
          与 src/infra_core/engine/ 形成 CODE_HYGIENE_DUPLICATE_BLOCK）。
        """
        arrays = _load_manifest_arrays()
        for mapping in arrays["CROSS"]:
            src = mapping.partition(":")[0]
            assert src.startswith("src/infra_core/engine/"), f"非引擎单源源路径: {src}"
            assert not re.match(r"^scripts/", src), f"memory-core 式源路径残留: {src}"
            assert "cross-dir" not in src, f"快照副本源路径回潮: {src}"

    def test_cross_dir_targets_are_flat_names(self):
        """部署目标名是生产目录下的平铺文件名（无子目录）。"""
        arrays = _load_manifest_arrays()
        for mapping in arrays["CROSS"]:
            dst = mapping.partition(":")[2]
            assert "/" not in dst, f"部署目标应为平铺文件名: {dst}"

    def test_no_double_claim_between_managed_and_cross_dir(self):
        """同一生产文件名不得同时出现在 MANAGED 与 CROSS_DIR 清单。"""
        arrays = _load_manifest_arrays()
        managed_targets = {Path(n).name for n in arrays["MANAGED"] + arrays["LIB"]}
        cross_targets = {m.partition(":")[2] for m in arrays["CROSS"]}
        overlap = managed_targets & cross_targets
        assert not overlap, f"双 claim 生产文件名: {overlap}"


class TestEngineSingleSourceConvergence:
    """INFRA-679 血统收敛契约：cross-dir 快照退役、引擎单源可追溯。"""

    def test_cross_dir_snapshot_directory_stays_retired(self):
        """webhook-scripts/cross-dir/ 快照目录不得复活（双副本根因）。"""
        cross_dir = REPO_ROOT / "webhook-scripts" / "cross-dir"
        assert not cross_dir.exists(), (
            "webhook-scripts/cross-dir/ 已随 INFRA-679 退役——新增部署源请直接"
            "登记 src/infra_core/engine/ 引擎单源，不得重建逐字节快照副本"
        )

    def test_lineage_documented_in_manifest(self):
        text = MANIFEST_PATH.read_text(encoding="utf-8")
        assert "memory-core" in text, "manifest 应记录 cross-dir 副本的 memory-core 血统"
        assert "INFRA-679" in text, "manifest 应记录 INFRA-679 单源收敛决策"

    def test_engine_sources_are_the_deploy_canonical_modules(self):
        """部署源必须是 CI/CLI 同源的引擎模块（python -m infra_core.engine.* 消费面）。"""
        arrays = _load_manifest_arrays()
        sources = {m.partition(":")[0] for m in arrays["CROSS"]}
        assert sources == {
            "src/infra_core/engine/extract_anchor.py",
            "src/infra_core/engine/evolution_utils.py",
            "src/infra_core/engine/evolution_adapters.py",
            "src/infra_core/engine/anchor_gate.py",
        }, f"CROSS_DIR 源集合漂移: {sorted(sources)}"
