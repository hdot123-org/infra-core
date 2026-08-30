"""Webhook-scripts manifest ownership contract tests（M5 shrink）.

webhook 生产同步的真源自本仓（architecture §7：webhook-scripts/MANIFEST.sh
迁 infra-core，memory-core 侧同名 manifest 已删除，过渡期不双 claim）。

本测试锁定三类不变量：
1. MANIFEST.sh 声明的每个受管文件在仓内真实存在（防 manifest 漂移）。
2. CROSS_DIR_MAPPINGS 源路径全部解析到本仓布局（webhook-scripts/cross-dir/），
   且不再出现 memory-core 式 scripts/ 源路径（VAL-SHRINK-005）。
3. cross-dir 副本与 memory-core 生产血统保持 sha256 可追溯（血缘注释存在）。

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
    """CROSS_DIR 源路径必须解析到本仓布局（不双 claim、不悬空）。"""

    def test_cross_dir_sources_exist(self):
        arrays = _load_manifest_arrays()
        assert len(arrays["CROSS"]) == 4, "锚点依赖链四件套应完整声明"
        for mapping in arrays["CROSS"]:
            src, _, _dst = mapping.partition(":")
            assert (REPO_ROOT / src).is_file(), f"CROSS_DIR 源不存在: {src}"

    def test_cross_dir_sources_use_infra_core_layout(self):
        """源路径必须是本仓 webhook-scripts/ 布局，禁止 memory-core 式 scripts/ 源。"""
        arrays = _load_manifest_arrays()
        for mapping in arrays["CROSS"]:
            src = mapping.partition(":")[0]
            assert src.startswith("webhook-scripts/"), f"非本仓布局源路径: {src}"
            assert not re.match(r"^scripts/", src), f"memory-core 式源路径残留: {src}"

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


class TestCrossDirLineage:
    """cross-dir 副本的生产血统声明（M5 迁移快照，非引擎模块）。"""

    def test_lineage_documented_in_manifest(self):
        text = MANIFEST_PATH.read_text(encoding="utf-8")
        assert "cross-dir" in text
        assert "memory-core" in text, "manifest 应记录 cross-dir 副本的 memory-core 血统"

    def test_cross_dir_readme_marks_deploy_lineage(self):
        readme = REPO_ROOT / "webhook-scripts" / "cross-dir" / "README.md"
        assert readme.is_file(), "cross-dir/README.md 应存在并标记部署血统"
        content = readme.read_text(encoding="utf-8")
        assert "sha256" in content
