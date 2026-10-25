"""数据结构定义。

定义整个项目共享的数据模型，包括弹幕指纹、抓取结果、检测报告等。
"""
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field


class DanmakuFingerprint(NamedTuple):
    """五元组物理指纹，唯一标识一条弹幕的物理特征。

    Attributes:
        content (str): 弹幕文本内容。
        progress_ms (int): 时间轴位置，毫秒整数。
        mode (int): 弹幕模式（1:滚动, 4:底部, 5:顶部等）。
        fontsize (int): 字号。
        color (int): 颜色十进制数值。
    """
    content: str
    progress_ms: int
    mode: int
    fontsize: int
    color: int


@dataclass(frozen=True)
class CrawledDanmaku:
    """一条线上弹幕的抓取结果。

    Attributes:
        fingerprint (DanmakuFingerprint): 五元组物理指纹。
        midhash (str): 发送者 midHash（线上值，用于错发归因）。
    """
    fingerprint: DanmakuFingerprint
    midhash: str

    def to_dict(self) -> dict:
        """转为可 JSON 落盘的字典。

        Returns:
            dict: 含 midhash 与五元组各字段的字典。
        """
        return {
            "midhash": self.midhash,
            "content": self.fingerprint.content,
            "progress_ms": self.fingerprint.progress_ms,
            "mode": self.fingerprint.mode,
            "fontsize": self.fingerprint.fontsize,
            "color": self.fingerprint.color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CrawledDanmaku":
        """从落盘字典还原。

        Args:
            data (dict): to_dict 产出的字典。

        Returns:
            CrawledDanmaku: 还原后的抓取结果。
        """
        return cls(
            fingerprint=DanmakuFingerprint(
                content=data["content"],
                progress_ms=int(data["progress_ms"]),
                mode=int(data["mode"]),
                fontsize=int(data["fontsize"]),
                color=int(data["color"]),
            ),
            midhash=data["midhash"],
        )


@dataclass(frozen=True)
class CrawlOk:
    """一个分P抓取完整成功。

    仅在该分P全段抓齐时产出，结果可直接进入比对。

    Attributes:
        part_num (int): 分P编号。
        cid (int): 分P 的 cid。
        segments_total (int): 该分P的总段数。
        online (Counter[DanmakuFingerprint]): 全量弹幕指纹计数。
        sender_map (dict[str, Counter[DanmakuFingerprint]]): 发送者映射，键为 midhash。
    """
    part_num: int
    cid: int
    segments_total: int
    online: Counter[DanmakuFingerprint]
    sender_map: dict[str, Counter[DanmakuFingerprint]]


@dataclass(frozen=True)
class CrawlFail:
    """一个分P抓取失败。

    任一段缺失即整体失败，该分P不进入比对，结果在报告中单列。

    Attributes:
        part_num (int): 分P编号。
        cid (int): 分P 的 cid。
        segments_total (int): 该分P的总段数。
        reason (str): 失败原因。
        failed_segment (int | None): 失败所在分段号，未开始抓取时为 None。
    """
    part_num: int
    cid: int
    segments_total: int
    reason: str
    failed_segment: int | None = None


CrawlResult = CrawlOk | CrawlFail


@dataclass(frozen=True)
class CrawlProgress:
    """抓取进度快照。

    Attributes:
        part_num (int): 当前分P编号。
        segment_done (int): 该分P已抓段数。
        segment_total (int): 该分P总段数。
        parts_done (int): 已结束的分P数，含失败。
        parts_total (int): 总分P数。
    """
    part_num: int
    segment_done: int
    segment_total: int
    parts_done: int
    parts_total: int


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
        midhash (str): 发送者 midHash。
        extra_count (int): 该发送者在 Extra 中的贡献条数。
        likely_source_part (int): 最可能的来源分P编号。
        match_rate (float): 与来源分P的匹配率。
        match_count (int): 匹配的弹幕数。
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
        part_num (int): 分P编号。
        online_count (int): 线上弹幕总数。
        expected_count (int): 本地应发弹幕数。
        extra_count (int): 多余弹幕数（线上比本地多）。
        unsent_count (int): 未发弹幕数（本地比线上多）。
        unsent_rate (float): 漏发比例。
        status (PartStatus): 检测状态。
        anomalies (list[SenderAnomaly]): 异常发送者列表（错发归因）。
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
        bvid (str): 视频 BV 号。
        title (str): 视频标题。
        total_parts (int): 总分P数，含抓取失败的。
        reports (list[PartReport]): 检测报告列表，只含抓取完整的分P。
        timestamp (str): 检测时间戳。
        failed_parts (list[CrawlFail]): 抓取失败的分P列表，不进入比对。
    """
    bvid: str
    title: str
    total_parts: int
    reports: list[PartReport]
    timestamp: str
    failed_parts: list[CrawlFail] = field(default_factory=list)


def _mask(value: str) -> str:
    """遮蔽凭据，保留首尾各 4 个字符，中间以 * 替代。

    Args:
        value (str): 待遮蔽的原始字符串。

    Returns:
        str: 遮蔽后的字符串，长度不超过 20。
    """
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 8:
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
    stars = min(len(value) - 8, 8)
    return f"{value[:4]}{'*' * stars}{value[-4:]}"


class AccountCredential(BaseModel):
    """已保存的账号凭据。

    Attributes:
        uid (int): 用户 UID。
        name (str): 用户昵称。
        sessdata (str): SESSDATA 值。
        level (int): 用户等级（-1=未知, 0-6）。
        is_valid (bool | None): 有效性，None=未检测, True=有效, False=失效。
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
