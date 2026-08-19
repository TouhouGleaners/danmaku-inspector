"""核心校验算法：错发检测 + 漏发检测。

核心公式：
- 错发: Extra = All - Expected（线上多了什么）
- 漏发: Unsent = Expected - All（我们少了什么）

错发归因：通过 midHash 贡献量过滤路人，跨P匹配找来源。
"""
import logging
from collections import Counter

from danmaku_inspector.types.models import DanmakuFingerprint, PartReport, PartStatus, SenderAnomaly
from danmaku_inspector.config.settings import InspectionConfig, DEFAULT_INSPECTION_CONFIG

logger = logging.getLogger(__name__)


def counter_total(counter: Counter) -> int:
    """计算 Counter 中所有元素的总数。

    Args:
        counter: 要计算的 Counter。

    Returns:
        所有元素的总数。
    """
    return sum(counter.values())


def inspect_part(
    part_num: int,
    expected: Counter[DanmakuFingerprint],
    online: Counter[DanmakuFingerprint],
    sender_map: dict[str, Counter[DanmakuFingerprint]],
    all_expected: dict[int, Counter[DanmakuFingerprint]],
    config: InspectionConfig = DEFAULT_INSPECTION_CONFIG,
) -> PartReport:
    """校验单个分P（错发 + 漏发）。

    Args:
        part_num: 当前分P编号。
        expected: 本地应发弹幕 Counter。
        online: 线上全量弹幕 Counter。
        sender_map: 发送者映射 {midhash: Counter}。
        all_expected: 所有分P的应发弹幕 {part_num: Counter}。
        config: 校验阈值配置。

    Returns:
        单个分P的检测报告。
    """
    online_count = counter_total(online)
    expected_count = counter_total(expected)

    # 核心公式
    extra = online - expected      # 错发: 线上多了什么
    unsent = expected - online     # 漏发: 我们少了什么

    extra_count = counter_total(extra)
    unsent_count = counter_total(unsent)
    unsent_rate = unsent_count / expected_count if expected_count > 0 else 0.0

    # 多余弹幕数 < 阈值，认为是路人散兵，不归因
    if extra_count < config.extra_threshold:
        # 漏发率在可接受范围内，显示正常
        if unsent_rate < config.unsent_rate_threshold:
            status = PartStatus.PASS
        else:
            status = PartStatus.UNSENT
        return PartReport(
            part_num=part_num,
            online_count=online_count,
            expected_count=expected_count,
            extra_count=extra_count,
            unsent_count=unsent_count,
            unsent_rate=unsent_rate,
            status=status,
        )

    # 遍历发送者，寻找错发归因
    anomalies = _find_anomalies(
        sender_map=sender_map,
        extra=extra,
        all_expected=all_expected,
        current_part=part_num,
        extra_threshold=config.extra_threshold,
        match_threshold=config.match_threshold,
    )

    # 综合判定状态
    mismatch_count = sum(a.extra_count for a in anomalies)
    mismatch_rate = mismatch_count / online_count if online_count > 0 else 0.0
    has_extra = mismatch_rate >= config.extra_rate_threshold
    has_unsent = unsent_rate >= config.unsent_rate_threshold

    if has_extra and has_unsent:
        status = PartStatus.BOTH
    elif has_extra:
        status = PartStatus.EXTRA
    elif has_unsent:
        status = PartStatus.UNSENT
    else:
        status = PartStatus.PASS

    return PartReport(
        part_num=part_num,
        online_count=online_count,
        expected_count=expected_count,
        extra_count=extra_count,
        unsent_count=unsent_count,
        unsent_rate=unsent_rate,
        status=status,
        anomalies=anomalies,
    )


def _find_anomalies(
    sender_map: dict[str, Counter[DanmakuFingerprint]],
    extra: Counter[DanmakuFingerprint],
    all_expected: dict[int, Counter[DanmakuFingerprint]],
    current_part: int,
    extra_threshold: int,
    match_threshold: float,
) -> list[SenderAnomaly]:
    """在 Extra 池中寻找异常发送者，尝试归因到其他分P。

    Args:
        sender_map: 发送者映射 {midhash: Counter}。
        extra: 多余弹幕 Counter。
        all_expected: 所有分P的应发弹幕。
        current_part: 当前分P编号。
        extra_threshold: 贡献条数阈值。
        match_threshold: 匹配率阈值。

    Returns:
        异常发送者列表。
    """
    anomalies = []

    for midhash, sender_counter in sender_map.items():
        # sender_extra = sender_online & Extra
        sender_extra = sender_counter & extra
        sender_extra_count = counter_total(sender_extra)

        # 贡献量不足，跳过
        if sender_extra_count < extra_threshold:
            continue

        # 跨P匹配：找最可能的来源分P
        best_part = -1
        best_rate = 0.0
        best_count = 0

        for other_part, other_expected in all_expected.items():
            if other_part == current_part:
                continue

            match = sender_extra & other_expected
            match_count = counter_total(match)
            match_rate = match_count / sender_extra_count

            if match_rate > best_rate:
                best_rate = match_rate
                best_part = other_part
                best_count = match_count

        # 匹配率 >= 阈值，记录异常
        if best_rate >= match_threshold:
            anomalies.append(SenderAnomaly(
                midhash=midhash,
                extra_count=sender_extra_count,
                likely_source_part=best_part,
                match_rate=best_rate,
                match_count=best_count,
            ))

    return anomalies


def inspect_all_parts(
    all_expected: dict[int, Counter[DanmakuFingerprint]],
    all_online: dict[int, tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]],
    config: InspectionConfig = DEFAULT_INSPECTION_CONFIG,
) -> list[PartReport]:
    """校验所有分P。

    Args:
        all_expected: {part_num: expected_counter} 映射。
        all_online: {part_num: (online_counter, sender_map)} 映射。
        config: 校验阈值配置。

    Returns:
        所有分P的检测报告列表。
    """
    reports = []

    for part_num in sorted(all_expected.keys()):
        if part_num not in all_online:
            logger.warning(f"P{part_num} 无线上数据，跳过")
            continue

        expected = all_expected[part_num]
        online, sender_map = all_online[part_num]

        report = inspect_part(
            part_num=part_num,
            expected=expected,
            online=online,
            sender_map=sender_map,
            all_expected=all_expected,
            config=config,
        )
        reports.append(report)

    return reports
