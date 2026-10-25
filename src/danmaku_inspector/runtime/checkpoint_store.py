"""爬取检查点存取。

按 (bvid, cid) 落盘已抓到的分段，供失败重跑时续传。
分P全段抓齐后由调用方删除；检查点存在即表示该分P上一次未抓完。
"""
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from danmaku_inspector.config.app_meta import AppInfo
from danmaku_inspector.types.models import CrawledDanmaku, DanmakuFingerprint

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1


@dataclass
class CrawlCheckpoint:
    """一个分P的抓取进度。

    Attributes:
        bvid (str): 视频 BV 号。
        cid (int): 分P 的 cid。
        part_num (int): 分P编号。
        segments_total (int): 该分P的总段数。
        segments (dict[int, list[CrawledDanmaku]]): 已抓成功的分段，键为段号。
        created_at (str): 首次落盘时间，ISO 8601 格式。
    """
    bvid: str
    cid: int
    part_num: int
    segments_total: int
    segments: dict[int, list[CrawledDanmaku]] = field(default_factory=dict)
    created_at: str = ""

    @property
    def fetched_segments(self) -> set[int]:
        """已抓成功的段号集合。"""
        return set(self.segments.keys())

    @property
    def is_complete(self) -> bool:
        """是否全段已抓齐。"""
        return len(self.segments) >= self.segments_total

    def aggregate(self) -> tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]:
        """汇总各分段数据。

        Returns:
            tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]:
                元素为（全量弹幕指纹计数, 发送者映射），发送者映射的键为 midhash。
        """
        online: Counter[DanmakuFingerprint] = Counter()
        sender_map: dict[str, Counter[DanmakuFingerprint]] = {}
        for entries in self.segments.values():
            for entry in entries:
                fp = entry.fingerprint
                online[fp] += 1
                sender_map.setdefault(entry.midhash, Counter())[fp] += 1
        return online, sender_map


class CheckpointStore:
    """爬取检查点的落盘存取。"""

    def __init__(self, root: Path | None = None) -> None:
        """初始化存储。

        Args:
            root (Path | None): 存放目录，默认 AppInfo.Paths.CRAWL_CACHE。
        """
        self._root = root or AppInfo.Paths.CRAWL_CACHE
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, bvid: str, cid: int) -> Path:
        """构造单个分P的检查点文件路径。

        Args:
            bvid (str): 视频 BV 号。
            cid (int): 分P 的 cid。

        Returns:
            Path: 检查点 JSON 文件路径。
        """
        return self._root / f"{bvid}_{cid}.json"

    def load(self, bvid: str, cid: int) -> CrawlCheckpoint | None:
        """读取检查点。

        Args:
            bvid (str): 视频 BV 号。
            cid (int): 分P 的 cid。

        Returns:
            CrawlCheckpoint | None: 文件不存在、损坏或版本不符时返回 None。
        """
        path = self._path(bvid, cid)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"检查点损坏，忽略并重抓: {path}, Error: {e}")
            return None

        # 根节点或字段结构不符时按损坏处理，避免异常冒出让该分P永久失败
        if not isinstance(data, dict):
            logger.warning(f"检查点根节点不是对象，忽略并重抓: {path}")
            return None

        if data.get("version") != _FORMAT_VERSION:
            logger.warning(f"检查点版本不符，忽略并重抓: {path}")
            return None

        try:
            raw_segments = data.get("segments", {})
            if not isinstance(raw_segments, dict):
                raise TypeError(f"segments 应为字典，实际为 {type(raw_segments).__name__}")
            segments = {
                int(seg_no): [CrawledDanmaku.from_dict(item) for item in items]
                for seg_no, items in raw_segments.items()
            }
            return CrawlCheckpoint(
                bvid=data["bvid"],
                cid=int(data["cid"]),
                part_num=int(data["part_num"]),
                segments_total=int(data["segments_total"]),
                segments=segments,
                created_at=data.get("created_at", ""),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            logger.warning(f"检查点内容不合法，忽略并重抓: {path}, Error: {e}")
            return None

    def save(self, checkpoint: CrawlCheckpoint) -> None:
        """整体覆盖写入检查点。

        Args:
            checkpoint (CrawlCheckpoint): 待落盘的检查点。
        """
        path = self._path(checkpoint.bvid, checkpoint.cid)
        payload = {
            "version": _FORMAT_VERSION,
            "bvid": checkpoint.bvid,
            "cid": checkpoint.cid,
            "part_num": checkpoint.part_num,
            "segments_total": checkpoint.segments_total,
            "created_at": checkpoint.created_at,
            "segments": {
                str(seg_no): [entry.to_dict() for entry in entries]
                for seg_no, entries in checkpoint.segments.items()
            },
        }
        # 先写临时文件再替换，避免写入中断留下损坏文件
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            tmp.replace(path)
        except OSError as e:
            logger.error(f"检查点写入失败: {path}, Error: {e}")

    def delete(self, bvid: str, cid: int) -> None:
        """删除检查点。

        Args:
            bvid (str): 视频 BV 号。
            cid (int): 分P 的 cid。
        """
        path = self._path(bvid, cid)
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"检查点删除失败: {path}, Error: {e}")
