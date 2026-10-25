"""分P抓取器。

按分段总数逐段抓取一个分P的线上弹幕，段级进度落盘供续传。
全段抓齐后汇总产出 CrawlOk 并清除检查点；任一段失败则整个分P产出 CrawlFail。
"""
import logging
import math
import time
from datetime import datetime
from typing import Callable

from danmaku_inspector.config.settings import NetworkConfig, DEFAULT_NETWORK_CONFIG
from danmaku_inspector.repo.bilibili.bili_api_client import (
    BiliApiClient,
    BiliApiError,
    BiliNetworkError,
    RiskControlError,
)
from danmaku_inspector.repo.bilibili.throttle import CrawlAborted, CrawlThrottle
from danmaku_inspector.runtime.checkpoint_store import CrawlCheckpoint, CheckpointStore
from danmaku_inspector.types.models import CrawlFail, CrawlOk, CrawlResult

logger = logging.getLogger(__name__)

# 检查点的最大续传年龄。超过则丢弃重建，不与新抓取的分段合并。
MAX_CHECKPOINT_AGE_SEC = 6 * 3600


def segment_count(duration_sec: int, segment_seconds: int) -> int:
    """按分P时长推算分段总数。

    分段号从 1 开始，每段覆盖 segment_seconds 秒的时间轴。

    Args:
        duration_sec (int): 分P时长（秒）。
        segment_seconds (int): 单段覆盖的时间轴长度（秒）。

    Returns:
        int: 分段总数，至少为 1；时长为 0 或参数非正时返回 1。
    """
    if duration_sec <= 0 or segment_seconds <= 0:
        return 1
    return max(1, math.ceil(duration_sec / segment_seconds))


class PartCrawler:
    """单个分P的抓取器。

    一次实例服务于一次 run，检查点持久化，限流与熔断由所有分P共享。
    """

    def __init__(
        self,
        client: BiliApiClient,
        throttle: CrawlThrottle,
        store: CheckpointStore,
        config: NetworkConfig = DEFAULT_NETWORK_CONFIG,
    ) -> None:
        """初始化抓取器。

        Args:
            client (BiliApiClient): B站 API 客户端。
            throttle (CrawlThrottle): 全局限流与熔断门。
            store (CheckpointStore): 检查点存取。
            config (NetworkConfig): 网络与调度配置。
        """
        self._client = client
        self._throttle = throttle
        self._store = store
        self._config = config

    def crawl(
        self,
        *,
        bvid: str,
        part_num: int,
        cid: int,
        avid: int,
        duration: int,
        on_segment: Callable[[int, int], None] | None = None,
    ) -> CrawlResult:
        """抓取一个分P的全量弹幕。

        Args:
            bvid (str): 视频 BV 号。
            part_num (int): 分P编号。
            cid (int): 分P 的 cid。
            avid (int): 视频 avid。
            duration (int): 分P时长（秒）。
            on_segment (Callable[[int, int], None] | None): 分段进度回调，
                接收（该P已抓段数, 该P总段数）。默认不回调。

        Returns:
            CrawlResult: 全段抓齐时为 CrawlOk，任一段失败时为 CrawlFail。
        """
        segments_total = segment_count(duration, self._config.segment_seconds)
        checkpoint = self._load_checkpoint(bvid, part_num, cid, segments_total)

        if checkpoint.fetched_segments:
            logger.info(
                f"P{part_num} 续传，时长 {duration}s，共 {segments_total} 段，"
                f"已抓段: {sorted(checkpoint.fetched_segments)}"
            )
        else:
            logger.info(f"P{part_num} 开始抓取，时长 {duration}s，共 {segments_total} 段")

        for seg in range(1, segments_total + 1):
            # 检查点已含该段时跳过网络请求
            if seg in checkpoint.segments:
                if on_segment:
                    on_segment(len(checkpoint.segments), segments_total)
                continue

            try:
                entries = self._fetch_segment(cid, avid, seg)
            except (RiskControlError, CrawlAborted, BiliApiError, BiliNetworkError) as e:
                logger.warning(f"P{part_num} 段{seg}/{segments_total} 失败: {e}")
                return CrawlFail(
                    part_num=part_num,
                    cid=cid,
                    segments_total=segments_total,
                    reason=str(e),
                    failed_segment=seg,
                )

            checkpoint.segments[seg] = entries
            self._store.save(checkpoint)
            if on_segment:
                on_segment(len(checkpoint.segments), segments_total)

        online, sender_map = checkpoint.aggregate()
        self._store.delete(bvid, cid)
        seg_sizes = "/".join(str(len(checkpoint.segments[s])) for s in range(1, segments_total + 1))
        logger.info(
            f"P{part_num} 抓取完成，共 {segments_total} 段 "
            f"{sum(online.values())} 条，各段: {seg_sizes}"
        )
        return CrawlOk(
            part_num=part_num,
            cid=cid,
            segments_total=segments_total,
            online=online,
            sender_map=sender_map,
        )

    def _load_checkpoint(
        self, bvid: str, part_num: int, cid: int, segments_total: int
    ) -> CrawlCheckpoint:
        """读取可用于续传的检查点。

        Args:
            bvid (str): 视频 BV 号。
            part_num (int): 分P编号。
            cid (int): 分P 的 cid。
            segments_total (int): 当前计算出的分段总数。

        Returns:
            CrawlCheckpoint: 命中且有效时返回已存进度，否则返回空进度。
        """
        existing = self._store.load(bvid, cid)

        if existing is not None:
            if existing.cid != cid or existing.segments_total != segments_total:
                logger.info(f"P{part_num} 检查点与当前参数不符，丢弃重抓")
            elif self._is_stale(existing):
                logger.warning(f"P{part_num} 检查点超过 {MAX_CHECKPOINT_AGE_SEC // 3600} 小时，作废重抓")
            else:
                return existing
            self._store.delete(bvid, cid)

        return CrawlCheckpoint(
            bvid=bvid,
            cid=cid,
            part_num=part_num,
            segments_total=segments_total,
            created_at=datetime.now().isoformat(),
        )

    @staticmethod
    def _is_stale(checkpoint: CrawlCheckpoint) -> bool:
        """判断检查点是否超过最大续传年龄。

        Args:
            checkpoint (CrawlCheckpoint): 待判断的检查点。

        Returns:
            bool: 超龄或创建时间不可解析时为 True。
        """
        if not checkpoint.created_at:
            return True
        try:
            created = datetime.fromisoformat(checkpoint.created_at)
        except ValueError:
            return True
        age = (datetime.now() - created).total_seconds()
        return age > MAX_CHECKPOINT_AGE_SEC

    def _fetch_segment(self, cid: int, avid: int, segment_index: int) -> list:
        """抓取单个分段。

        网络错误按指数退避重试，最多尝试 config.max_retries 次；
        风控错误不重试，直接触发熔断并抛出。

        Args:
            cid (int): 分P 的 cid。
            avid (int): 视频 avid。
            segment_index (int): 分段号，从 1 开始。

        Returns:
            list: 该分段内的 CrawledDanmaku 列表，可能为空。

        Raises:
            RiskControlError: 被B站风控，已触发熔断。
            CrawlAborted: 熔断已触发。
            BiliApiError: B站返回业务错误，不重试。
            BiliNetworkError: 重试次数耗尽后的网络错误。
        """
        attempts = max(1, self._config.max_retries)
        last_error: BiliNetworkError | None = None

        for attempt in range(attempts):
            try:
                self._throttle.wait()
                return self._client.fetch_segment(cid, avid, segment_index)
            except RiskControlError as e:
                self._throttle.trip(str(e))
                raise
            except BiliApiError:
                raise
            except BiliNetworkError as e:
                last_error = e
                if attempt + 1 >= attempts:
                    raise
                delay = self._config.retry_backoff * (2 ** attempt)
                logger.debug(
                    f"cid={cid} 段{segment_index} 第{attempt + 1}次失败，"
                    f"{delay:.1f}s 后重试: {e}"
                )
                time.sleep(delay)

        raise last_error if last_error else BiliNetworkError("未知抓取失败")
