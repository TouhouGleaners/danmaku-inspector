"""数据结构定义。

定义整个项目共享的数据模型，包括弹幕指纹、检测报告等。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field


class DanmakuFingerprint(NamedTuple):
    """五元组物理指纹，用于唯一标识一条弹幕的物理特征。

    Attributes:
        content: 弹幕文本内容。
        progress_ms: 时间轴位置，毫秒整数。
        mode: 弹幕模式 (1:滚动, 4:底部, 5:顶部等)。
        fontsize: 字号。
        color: 颜色十进制数值。
    """
    content: str
    progress_ms: int
    mode: int
    fontsize: int
    color: int


class PartStatus(str, Enum):
    """分P检测状态。

    Attributes:
        PASS: 通过，无异常。
        EXTRA: 有错发。
        UNSENT: 有漏发。
        BOTH: 错发 + 漏发。
    """
    PASS = "PASS"
    EXTRA = "EXTRA"
    UNSENT = "UNSENT"
    BOTH = "BOTH"


@dataclass
class SenderAnomaly:
    """单个发送者的异常信息（错发归因）。

    Attributes:
        midhash: 发送者 midHash。
        extra_count: 该发送者在 Extra 中的贡献条数。
        likely_source_part: 最可能的来源分P编号。
        match_rate: 与来源分P的匹配率。
        match_count: 匹配的弹幕数。
    """
    midhash: str
    extra_count: int
    likely_source_part: int
    match_rate: float
    match_count: int


@dataclass
class PartReport:
    """单个分P的检测报告。

    Attributes:
        part_num: 分P编号。
        online_count: 线上弹幕总数。
        expected_count: 本地应发弹幕数。
        extra_count: 多余弹幕数（线上比本地多）。
        unsent_count: 未发弹幕数（本地比线上多）。
        unsent_rate: 漏发比例。
        status: 检测状态。
        anomalies: 异常发送者列表（错发归因）。
    """
    part_num: int
    online_count: int
    expected_count: int
    extra_count: int
    unsent_count: int
    unsent_rate: float
    status: PartStatus
    anomalies: list[SenderAnomaly] = field(default_factory=list)


@dataclass
class InspectionReport:
    """整体检测报告。

    Attributes:
        bvid: 视频 BV 号。
        title: 视频标题。
        total_parts: 总分P数。
        reports: 各分P的检测报告列表。
        timestamp: 检测时间戳。
    """
    bvid: str
    title: str
    total_parts: int
    reports: list[PartReport]
    timestamp: str


def _mask(value: str) -> str:
    """遮蔽凭据：保留前4后4，中间用 * 替代，总长不超过 20。"""
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 8:
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
    stars = min(len(value) - 8, 8)
    return f"{value[:4]}{'*' * stars}{value[-4:]}"


class AccountCredential(BaseModel):
    """已保存的账号凭据。

    Attributes:
        uid: 用户 UID。
        name: 用户昵称。
        sessdata: SESSDATA 值。
        level: 用户等级 (-1=未知, 0-6)。
        is_valid: 是否有效 (None=未检测, True=有效, False=失效)。
    """
    uid: int = 0
    name: str = ""
    sessdata: str = ""
    level: int = -1
    is_valid: bool | None = Field(default=None, exclude=True)

    @property
    def masked_sessdata(self) -> str:
        """遮蔽后的 SESSDATA。"""
        return _mask(self.sessdata)
