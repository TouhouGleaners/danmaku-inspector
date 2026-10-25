"""校验流程编排。

协调本地解析、线上抓取与比对，不依赖 Qt。
进度经纯 Python 回调上报。
"""
import logging
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from danmaku_inspector.types.models import (
    CrawlFail,
    CrawlOk,
    CrawlProgress,
    CrawlResult,
    DanmakuFingerprint,
    InspectionReport,
)
from danmaku_inspector.config.settings import InspectionConfig, NetworkConfig, DEFAULT_INSPECTION_CONFIG, DEFAULT_NETWORK_CONFIG
from danmaku_inspector.repo.local.parser import parse_all_parts
from danmaku_inspector.repo.bilibili.bili_api_client import BiliApiClient
from danmaku_inspector.repo.bilibili.throttle import CrawlThrottle
from danmaku_inspector.runtime.checkpoint_store import CheckpointStore
from danmaku_inspector.service.crawler import PartCrawler, segment_count
from danmaku_inspector.service.inspector import inspect_all_parts

logger = logging.getLogger(__name__)

# 兜底：单个分P的未知异常不该拖垮整轮抓取
_SAFE_FAIL = "未知异常: {}"


class InspectionOrchestrator:
    """校验流程编排器。

    负责协调各模块完成校验流程，不依赖 Qt。
    """

    def __init__(
        self,
        inspection_config: InspectionConfig = DEFAULT_INSPECTION_CONFIG,
        network_config: NetworkConfig = DEFAULT_NETWORK_CONFIG,
    ) -> None:
        """初始化编排器。

        Args:
            inspection_config (InspectionConfig): 校验阈值配置。
            network_config (NetworkConfig): 网络与调度配置。
        """
        self._inspection_config = inspection_config
        self._network_config = network_config
        self.all_expected: dict[int, Counter[DanmakuFingerprint]] = {}
        self.all_online: dict[int, tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]] = {}
        self.report: InspectionReport | None = None

    def run(
        self,
        bvid: str,
        sessdata: str,
        xml_dir: str,
        on_status: Callable[[str], None] | None = None,
        on_progress: Callable[[CrawlProgress], None] | None = None,
    ) -> InspectionReport:
        """执行校验流程。

        抓取按分P为原子单位执行，未抓齐的分P记为失败并置于
        InspectionReport.failed_parts，不进入比对。

        Args:
            bvid (str): 视频 BV 号。
            sessdata (str): SESSDATA 值。
            xml_dir (str): 本地 XML 文件目录。
            on_status (Callable[[str], None] | None): 状态回调，接收可直接显示的状态字符串。
            on_progress (Callable[[CrawlProgress], None] | None): 进度回调，接收 CrawlProgress 快照。
                两个回调可能从工作线程调用，调用方需保证线程安全。

        Returns:
            InspectionReport: 整体检测报告。

        Raises:
            ValueError: 未找到 XML 文件，或没有可校验的分P。
            BiliNetworkError: 获取视频信息失败。
        """
        # 1. 解析本地 XML
        if on_status:
            on_status("正在解析本地文件...")

        self.all_expected = parse_all_parts(Path(xml_dir))
        if not self.all_expected:
            raise ValueError("未找到任何 XML 文件")

        # 2. 一次 run 复用同一个客户端，避免每个请求都新建短命连接
        with BiliApiClient(sessdata, self._network_config) as client:
            if on_status:
                on_status("正在获取视频信息...")

            video_info = client.get_video_info(bvid)

            # 3. 构建抓取目标：本地有 XML 且线上有对应分P
            targets = self._build_targets(video_info)
            if not targets:
                raise ValueError("没有可校验的分P")

            # 4. 抓取线上弹幕
            throttle = CrawlThrottle(
                rate_per_second=self._network_config.rate_per_second,
                burst=self._network_config.rate_burst,
            )
            results = self._crawl_parts(
                client=client,
                throttle=throttle,
                bvid=bvid,
                avid=video_info["aid"],
                targets=targets,
                on_status=on_status,
                on_progress=on_progress,
            )

        # 5. 拆分：完整的进比对，失败的单列
        self.all_online = {}
        failed_parts: list[CrawlFail] = []
        for result in results.values():
            if isinstance(result, CrawlOk):
                self.all_online[result.part_num] = (result.online, result.sender_map)
            else:
                failed_parts.append(result)
        failed_parts.sort(key=lambda f: f.part_num)

        if throttle.tripped:
            logger.warning(f"本轮抓取被熔断: {throttle.reason}")

        # 6. 执行校验（只比对完整的分P）
        if on_status:
            on_status("正在分析...")

        reports = inspect_all_parts(
            all_expected=self.all_expected,
            all_online=self.all_online,
            config=self._inspection_config,
        )

        # 7. 构建报告
        self.report = InspectionReport(
            bvid=bvid,
            title=video_info["title"],
            total_parts=len(results),
            reports=reports,
            timestamp=datetime.now().isoformat(),
            failed_parts=failed_parts,
        )

        return self.report

    def _build_targets(self, video_info: dict) -> list[tuple[int, int, int]]:
        """构建抓取目标列表。

        Args:
            video_info (dict): get_video_info 返回的视频元数据。

        Returns:
            list[tuple[int, int, int]]: （分P编号, cid, 时长秒）列表，按分P编号升序。
        """
        pages: dict[int, dict] = video_info["pages"]
        targets: list[tuple[int, int, int]] = []

        for part_num in sorted(self.all_expected.keys()):
            page = pages.get(part_num)
            if page is None:
                logger.warning(f"P{part_num} 本地有 XML 但线上无对应分P，跳过")
                continue
            targets.append((part_num, page["cid"], page["duration"]))

        return targets

    def _crawl_parts(
        self,
        client: BiliApiClient,
        throttle: CrawlThrottle,
        bvid: str,
        avid: int,
        targets: list[tuple[int, int, int]],
        on_status: Callable[[str], None] | None,
        on_progress: Callable[[CrawlProgress], None] | None,
    ) -> dict[int, CrawlResult]:
        """并发抓取所有目标分P。

        每个分P为独立任务，限流与熔断由 throttle 全局共享。
        并发度只影响同时排队的任务数，不改变全局速率上限。

        Args:
            client (BiliApiClient): B站 API 客户端。
            throttle (CrawlThrottle): 全局限流与熔断门。
            bvid (str): 视频 BV 号。
            avid (int): 视频 avid。
            targets (list[tuple[int, int, int]]): 抓取目标列表。
            on_status (Callable[[str], None] | None): 状态回调。
            on_progress (Callable[[CrawlProgress], None] | None): 进度回调。

        Returns:
            dict[int, CrawlResult]: 分P编号到抓取结果的映射。
        """
        crawler = PartCrawler(client, throttle, CheckpointStore(), self._network_config)

        parts_total = len(targets)
        results: dict[int, CrawlResult] = {}
        lock = threading.Lock()
        finished = 0

        def work(part_num: int, cid: int, duration: int) -> CrawlResult:
            """抓取单个分P，供线程池调度。

            Args:
                part_num (int): 分P编号。
                cid (int): 分P 的 cid。
                duration (int): 分P时长（秒）。

            Returns:
                CrawlResult: 该分P的抓取结果。
            """
            def on_segment(seg_done: int, seg_total: int) -> None:
                """转发分段进度到上层回调。

                Args:
                    seg_done (int): 该分P已抓段数。
                    seg_total (int): 该分P总段数。
                """
                if not on_progress:
                    return
                with lock:
                    parts_done = finished
                on_progress(CrawlProgress(
                    part_num=part_num,
                    segment_done=seg_done,
                    segment_total=seg_total,
                    parts_done=parts_done,
                    parts_total=parts_total,
                ))

            return crawler.crawl(
                bvid=bvid,
                part_num=part_num,
                cid=cid,
                avid=avid,
                duration=duration,
                on_segment=on_segment,
            )

        workers = max(1, self._network_config.part_concurrency)
        logger.info(
            f"开始抓取 {parts_total} 个分P，并发 {workers}，"
            f"速率 {self._network_config.rate_per_second}/s"
        )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(work, part_num, cid, duration): (part_num, cid, duration)
                for part_num, cid, duration in targets
            }

            for future in as_completed(futures):
                part_num, cid, duration = futures[future]
                try:
                    result = future.result()
                except Exception as e:  # 兜底：未知异常只废这一个P
                    logger.exception(f"P{part_num} 抓取出现未知异常")
                    result = CrawlFail(
                        part_num=part_num,
                        cid=cid,
                        segments_total=segment_count(duration, self._network_config.segment_seconds),
                        reason=_SAFE_FAIL.format(e),
                    )

                with lock:
                    results[result.part_num] = result
                    finished += 1
                    parts_done = finished

                if on_status:
                    if isinstance(result, CrawlOk):
                        on_status(f"已完成 P{result.part_num} ({parts_done}/{parts_total})")
                    else:
                        on_status(f"P{result.part_num} 抓取失败 ({parts_done}/{parts_total})")

        return results
