"""数据结构定义"""
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple


class PartStatus(str, Enum):
    """分P检测状态。"""
    PASS = "PASS"           # 通过
    EXTRA = "EXTRA"         # 有错发
    UNSENT = "UNSENT"       # 有漏发
    BOTH = "BOTH"           # 错发 + 漏发


class DanmakuFingerprint(NamedTuple):
    """五元组物理指纹，用于唯一标识一条弹幕的物理特征。"""
    content: str        # 弹幕文本内容
    progress_ms: int    # 时间轴位置，毫秒整数
    mode: int           # 弹幕模式: 1滚动, 4底部, 5顶部等
    fontsize: int       # 字号
    color: int          # 颜色十进制数值


@dataclass
class SenderAnomaly:
    """单个发送者的异常信息（错发归因）。"""
    midhash: str                # 发送者 midHash
    extra_count: int            # 在 Extra 中的贡献条数
    likely_source_part: int     # 最可能的来源分P编号
    match_rate: float           # 与来源分P的匹配率
    match_count: int            # 匹配的弹幕数


@dataclass
class PartReport:
    """单个分P的检测报告。"""
    part_num: int
    online_count: int           # 线上弹幕总数
    expected_count: int         # 本地应发弹幕数
    extra_count: int            # 多余弹幕数（错发）
    unsent_count: int           # 未发弹幕数（漏发）
    unsent_rate: float          # 漏发比例
    status: PartStatus
    anomalies: list[SenderAnomaly] = field(default_factory=list)


@dataclass
class InspectionReport:
    """整体检测报告。"""
    bvid: str
    title: str
    total_parts: int
    reports: list[PartReport]
    timestamp: str