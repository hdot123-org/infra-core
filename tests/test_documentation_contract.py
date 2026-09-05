"""文档契约测试（docs-and-governance feature）。

锁定 docs/onboarding/consumer-onboarding.md 与 docs/architecture.md 的公告链路文档契约：
- consumer-onboarding.md 含"升级分发（公告规则）"章节
- 七项语义齐全（声明即接入 / 接单形态 / 公告粒度 / 同 tag 幂等 / Mac 离线兜底 /
  已知限制 / 与 §5 手动 bump 边界划分）
- 已知限制必须包含 2026-09-04 平台行为实证（draft→publish 对旧 release 不触发）
- 无夸大措辞（"必达" / "保证送达" / "100%" 类关键词零命中）
- docs/architecture.md 含公告链路章节
- 链路要素与生产配置逐项一致（URL / hook id / 脚本 / 路由键 / skill / 核心语义）

风格对齐 tests/test_release_announce_contract.py。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.schema

REPO_ROOT = Path(__file__).resolve().parent.parent
ONBOARDING_PATH = REPO_ROOT / "docs" / "onboarding" / "consumer-onboarding.md"
ARCHITECTURE_PATH = REPO_ROOT / "docs" / "architecture.md"


def _load_onboarding() -> str:
    """Load consumer-onboarding.md content."""
    if not ONBOARDING_PATH.exists():
        pytest.fail(f"consumer-onboarding.md not found at {ONBOARDING_PATH}")
    return ONBOARDING_PATH.read_text(encoding="utf-8")


def _load_architecture() -> str:
    """Load docs/architecture.md content."""
    if not ARCHITECTURE_PATH.exists():
        pytest.fail(f"architecture.md not found at {ARCHITECTURE_PATH}")
    return ARCHITECTURE_PATH.read_text(encoding="utf-8")


def test_onboarding_announcement_section_exists():
    """consumer-onboarding.md 含"升级分发（公告规则）"章节。"""
    content = _load_onboarding()
    # 章节标题匹配（支持中文或英文同义标题）
    pattern = r"^##\s+.*(?:升级分发|公告规则|announcement|broadcast).*"
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
    assert match is not None, (
        "consumer-onboarding.md must contain a section about upgrade announcement / broadcast rules"
    )


def test_onboarding_seven_semantics_complete():
    """七项语义齐全（声明即接入 / 接单形态 / 公告粒度 / 同 tag 幂等 /
    Mac 离线兜底 / 已知限制 / 与 §5 边界划分）。"""
    content = _load_onboarding()

    # 语义①：声明即接入（engineConsumer: true）
    assert re.search(r"engineConsumer:\s*true", content), (
        "Must mention engineConsumer: true as the routing key"
    )

    # 语义②：接单形态（droid 会话 / release-gateway skill）
    assert re.search(r"(?:droid\s+会话|session|release-gateway)", content), (
        "Must mention droid session or release-gateway skill for order-taking"
    )

    # 语义③：公告粒度（每次 release 含 patch）
    assert re.search(r"(?:每次|全量|含\s*patch|every\s+release)", content, re.IGNORECASE), (
        "Must mention announcement granularity includes every release with patch"
    )

    # 语义④：同 tag 幂等（幂等锁 / 重复公告）
    assert re.search(r"(?:幂等|idempotent|per-tag\s+锁|重复)", content, re.IGNORECASE), (
        "Must mention per-tag idempotency"
    )

    # 语义⑤：Mac 离线兜底（下次发版 / 手动 reconcile）
    assert re.search(
        r"(?:Mac\s+离线|离线.*兜底|手动\s*reconcile|下次发版)", content, re.IGNORECASE
    ), "Must mention Mac offline fallback (next release or manual reconcile)"

    # 语义⑥：已知限制（HTTP 200 ≠ 接单成功 / 离线窗口）
    assert re.search(
        r"(?:HTTP\s+200|200\s*≠|已知限制|known\s+limitation)", content, re.IGNORECASE
    ), "Must mention known limitations (HTTP 200 ≠ success, offline window)"

    # 语义⑦：与 §5 手动 bump 边界划分（已声明 vs 未声明）
    assert re.search(r"(?:§5|手动\s*bump|边界划分|未声明.*手动)", content, re.IGNORECASE), (
        "Must clarify boundary with §5 manual bump guide"
    )


def test_onboarding_platform_behavior_limitation():
    """已知限制必须包含 2026-09-04 平台行为实证（draft→publish 对旧 release 不触发）。"""
    content = _load_onboarding()

    # 平台行为：draft→publish 重发对旧 release 不触发
    assert re.search(
        r"(?:draft.*publish|旧\s*release|tag\s+commit.*早于|2026-09-04)",
        content,
        re.IGNORECASE,
    ), (
        "Known limitations must mention 2026-09-04 platform behavior: "
        "draft→publish re-publish of old releases (tag commit earlier than workflow) does not trigger"
    )


def test_onboarding_retry_window_clarification():
    """M2 scrutiny 纠偏 3a：必须明确重试窗口仅限 run 内 15-30s（--retry 3），窗口级离线不重试不补发。"""
    content = _load_onboarding()

    # 必须提及 run 内有限重试（--retry 3 / 15-30s）
    assert re.search(
        r"(?:run\s+内.*有限.*重试|15-30s.*curl.*重试|--retry\s+3)",
        content,
        re.IGNORECASE,
    ), (
        "Must clarify retry window: run-level 15-30s curl retry (--retry 3), window-level offline not retried"
    )


def test_onboarding_dirty_tree_tracked_scope():
    """M2 scrutiny 纠偏 3b：必须说明工作树脏检测仅覆盖 tracked 改动，untracked 不拦截。"""
    content = _load_onboarding()

    # 必须说明 dirty tree detection 仅覆盖 tracked 文件
    assert re.search(
        r"(?:工作树脏检测.*覆盖\s+tracked|untracked\s+文件不拦截|tracked.*改动.*untracked.*不拦截)",
        content,
        re.IGNORECASE,
    ), "Must clarify dirty tree detection covers tracked changes only, untracked files not blocked"


def test_onboarding_cloudflare_access_limitation():
    """M2 scrutiny 纠偏 3c：必须说明公网公告当前被 Cloudflare Access 拦 302，Service Token 生效前兜底=手动 reconcile。"""
    content = _load_onboarding()

    # 必须提及 Cloudflare Access 302 与 Service Token
    assert re.search(
        r"(?:Cloudflare\s+Access.*302|Service\s+Token.*兜底|CF-Access-Client-Id)",
        content,
        re.IGNORECASE,
    ), (
        "Must mention Cloudflare Access 302 limitation and Service Token fallback to manual reconcile"
    )


def test_onboarding_no_exaggerated_claims():
    """文档不得含夸大措辞（"必达" / "保证送达" / "100%" 类关键词零命中）。"""
    content = _load_onboarding()

    # 扫描夸大措辞
    exaggerated_patterns = [
        r"必达",
        r"保证送达",
        r"100%",
        r"绝对.*送达",
        r"永不丢失",
        r"guaranteed.*delivery",
        r"100\s*percent",
    ]

    for pattern in exaggerated_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        assert match is None, (
            f"Documentation must not contain exaggerated claims: found '{match.group()}'"
        )


def test_architecture_announcement_chain_section_exists():
    """docs/architecture.md 含公告链路章节。"""
    content = _load_architecture()

    # 章节标题匹配
    pattern = r"^##\s+.*(?:公告|announcement|broadcast|链路).*"
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
    assert match is not None, "docs/architecture.md must contain a section about announcement chain"


def test_architecture_chain_elements_consistent():
    """链路要素与生产配置逐项一致（URL / hook id / 脚本 / 路由键 / skill / 核心语义）。"""
    content = _load_architecture()

    # URL 要素
    assert re.search(
        r"https://ci-webhook\.exa\.edu\.kg/hooks/release-broadcast",
        content,
    ), "Must mention the exact broadcast URL: https://ci-webhook.exa.edu.kg/hooks/release-broadcast"

    # Hook ID
    assert re.search(r"release-broadcast", content), "Must mention hook ID: release-broadcast"

    # 脚本
    assert re.search(r"trigger-release\.sh", content), "Must mention trigger-release.sh script"

    # 路由键
    assert re.search(r"engineConsumer:\s*true", content), (
        "Must mention routing key: engineConsumer: true"
    )

    # 接单 skill
    assert re.search(r"release-gateway", content), "Must mention release-gateway skill"

    # 核心语义：fire-and-forget / 2xx 送达 / 非 2xx 告警
    assert re.search(
        r"(?:fire-and-forget|2xx|非\s*2xx|告警|warning)",
        content,
        re.IGNORECASE,
    ), "Must mention core semantics: fire-and-forget, 2xx = delivered, non-2xx = warning"

    # 核心语义：per-tag 幂等
    assert re.search(r"(?:per-tag|幂等|idempotent)", content, re.IGNORECASE), (
        "Must mention per-tag idempotency"
    )

    # 核心语义：逐仓错误隔离
    assert re.search(r"(?:错误隔离|error\s+isolation|逐仓)", content, re.IGNORECASE), (
        "Must mention per-consumer error isolation"
    )


def test_architecture_platform_behavior_limitation():
    """docs/architecture.md 已知限制必须包含平台行为实证（draft→publish 对旧 release 不触发）。"""
    content = _load_architecture()

    # 平台行为：draft→publish 重发对旧 release 不触发
    assert re.search(
        r"(?:draft.*publish|旧\s*release|tag\s+commit.*早于|2026-09-04)",
        content,
        re.IGNORECASE,
    ), (
        "Known limitations must mention 2026-09-04 platform behavior: "
        "draft→publish re-publish of old releases does not trigger announcement"
    )


def test_onboarding_polling_trigger_surface():
    """VAL-ANN-029: consumer-onboarding.md 必须说明轮询触发面为默认触发机制。"""
    content = _load_onboarding()

    # 必须说明轮询为默认触发面
    assert re.search(r"(?:轮询.*默认|polling.*default)", content, re.IGNORECASE), (
        "Must clarify that polling is the default trigger mechanism"
    )


def test_onboarding_launchd_timer():
    """VAL-ANN-030: consumer-onboarding.md 必须说明宿主 launchd 定时器（300s 间隔）。"""
    content = _load_onboarding()

    # 必须提及 launchd 或定时器
    assert re.search(r"(?:launchd|定时器|timer|300.*秒|300s)", content, re.IGNORECASE), (
        "Must mention launchd timer with 300s interval"
    )


def test_onboarding_push_surface_sleep():
    """VAL-ANN-031: consumer-onboarding.md 必须说明推送面休眠机制（RELEASE_BROADCAST_URL 删除即休眠）。"""
    content = _load_onboarding()

    # 必须提及推送面休眠
    assert re.search(
        r"(?:推送面.*休眠|push.*sleep|RELEASE_BROADCAST_URL.*删除)", content, re.IGNORECASE
    ), "Must mention push surface sleep mechanism (delete RELEASE_BROADCAST_URL to sleep)"

    # 必须说明可唤醒
    assert re.search(r"(?:可唤醒|wake|恢复.*secret|restore.*secret)", content, re.IGNORECASE), (
        "Must mention that push surface can be woken up by restoring the secret"
    )


def test_onboarding_dual_trigger_idempotent():
    """VAL-ANN-032: consumer-onboarding.md 必须说明双触发幂等共存（推送+轮询）。"""
    content = _load_onboarding()

    # 必须提及双触发共存
    assert re.search(r"(?:双触发|dual\s+trigger|推送.*轮询|push.*poll)", content, re.IGNORECASE), (
        "Must mention dual trigger (push + polling) coexistence"
    )

    # 必须说明幂等锁保证只派发一次
    assert re.search(
        r"(?:幂等.*锁|idempotent.*lock|只派发一次|only\s+dispatch\s+once)", content, re.IGNORECASE
    ), "Must clarify that idempotent lock ensures only one dispatch per tag"


def test_architecture_polling_trigger_surface():
    """VAL-ANN-029: docs/architecture.md 必须说明轮询触发面（poll-releases.sh）为默认触发机制。"""
    content = _load_architecture()

    # 必须提及 poll-releases.sh
    assert re.search(r"poll-releases\.sh", content), (
        "Must mention poll-releases.sh as the polling trigger mechanism"
    )

    # 必须说明轮询为默认触发面
    assert re.search(r"(?:轮询.*默认|polling.*default)", content, re.IGNORECASE), (
        "Must clarify that polling is the default trigger mechanism"
    )


def test_architecture_launchd_timer():
    """VAL-ANN-030: docs/architecture.md 必须说明宿主 launchd 定时器（300s 间隔）。"""
    content = _load_architecture()

    # 必须提及 launchd 或定时器
    assert re.search(r"(?:launchd|定时器|timer|300.*秒|300s)", content, re.IGNORECASE), (
        "Must mention launchd timer with 300s interval"
    )


def test_architecture_push_surface_sleep():
    """VAL-ANN-031: docs/architecture.md 必须说明推送面休眠机制（RELEASE_BROADCAST_URL 删除即休眠）。"""
    content = _load_architecture()

    # 必须提及推送面休眠
    assert re.search(
        r"(?:推送面.*休眠|push.*sleep|RELEASE_BROADCAST_URL.*删除)", content, re.IGNORECASE
    ), "Must mention push surface sleep mechanism (delete RELEASE_BROADCAST_URL to sleep)"

    # 必须说明可唤醒
    assert re.search(r"(?:可唤醒|wake|恢复.*secret|restore.*secret)", content, re.IGNORECASE), (
        "Must mention that push surface can be woken up by restoring the secret"
    )


def test_architecture_dual_trigger_idempotent():
    """VAL-ANN-032: docs/architecture.md 必须说明双触发幂等共存（推送+轮询）。"""
    content = _load_architecture()

    # 必须提及双触发共存
    assert re.search(r"(?:双触发|dual\s+trigger|推送.*轮询|push.*poll)", content, re.IGNORECASE), (
        "Must mention dual trigger (push + polling) coexistence"
    )

    # 必须说明幂等锁保证只派发一次
    assert re.search(
        r"(?:幂等.*锁|idempotent.*lock|只派发一次|only\s+dispatch\s+once)", content, re.IGNORECASE
    ), "Must clarify that idempotent lock ensures only one dispatch per tag"


def test_onboarding_permission_sync_covenant_section_exists():
    """VAL-DS-036: consumer-onboarding.md 必须含权限同步守则节（§7）。

    引擎可复用 workflow 顶层 permissions 新增条目时，消费方薄调用方必须同步放行，
    否则 reusable-workflow 权限子集规则不满足 → startup_failure。
    """
    content = _load_onboarding()

    # 必须存在权限同步守则章节
    pattern = r"^##\s+\d+\.\s+.*(?:权限同步|permissions?.*sync|reusable.*workflow.*permissions).*"
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
    assert match is not None, (
        "consumer-onboarding.md must contain a section about reusable workflow permissions sync covenant"
    )


def test_onboarding_permission_sync_covenant_content():
    """VAL-DS-036: 权限同步守则必须包含核心原则与实例。

    核心原则：调用方授予集必须覆盖 callee 顶层声明集。
    实例：infra-core v0.11.1 actions: read 事件。
    """
    content = _load_onboarding()

    # 核心原则：caller 必须覆盖 callee 权限
    assert re.search(
        r"(?:调用方.*覆盖|caller.*cover|授予集.*覆盖|permissions.*子集|startup_failure)",
        content,
        re.IGNORECASE,
    ), (
        "Permission sync covenant must state that caller permissions must cover "
        "callee top-level permissions to avoid startup_failure"
    )

    # 实例：actions: read
    assert re.search(r"actions:\s*read", content), (
        "Permission sync covenant must mention the actions: read instance from infra-core v0.11.1"
    )

    # 实操规则：升级引擎 pin 时核对
    assert re.search(
        r"(?:升级.*pin.*核对|upgrade.*pin.*check|升级.*infra-core.*核对)",
        content,
        re.IGNORECASE,
    ), (
        "Permission sync covenant must include the rule to verify caller permissions when upgrading infra-core pin"
    )
