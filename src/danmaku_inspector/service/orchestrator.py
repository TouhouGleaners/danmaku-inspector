"""业务流程编排。

负责校验流程的编排，不依赖 Qt。
"""
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable

from danmaku_inspector.types.models import DanmakuFingerprint, InspectionReport
from danmaku_inspector.config.settings import InspectionConfig, NetworkConfig, DEFAULT_INSPECTION_CONFIG, DEFAULT_NETWORK_CONFIG
from danmaku_inspector.repo.local.parser import parse_all_parts
from danmaku_inspector.repo.bilibili.fetcher import get_video_info, fetch_part
from danmaku_inspector.service.inspector import inspect_all_parts

logger = logging.getLogger(__name__)


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
            inspection_config: 校验阈值配置。
            network_config: 网络请求配置。
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
    ) -> InspectionReport:
        """执行校验流程。

        Args:
            bvid: 视频 BV 号。
            sessdata: SESSDATA 值。
            xml_dir: 本地 XML 文件目录。
            on_status: 状态回调函数，接收状态字符串。

        Returns:
            整体检测报告。

        Raises:
            ValueError: 未找到 XML 文件或没有可校验的分P。
            RuntimeError: 被B站风控时抛出。
        """
        # 1. 解析本地 XML
        if on_status:
            on_status("正在解析本地文件...")

        xml_path = Path(xml_dir)
        self.all_expected = parse_all_parts(xml_path)
        if not self.all_expected:
            raise ValueError("未找到任何 XML 文件")

        # 2. 获取视频信息
        if on_status:
            on_status("正在获取视频信息...")

        video_info = get_video_info(bvid, sessdata)

        # 3. 构建 cid 映射
        part_cids: dict[int, int] = {}
        for part_num in self.all_expected.keys():
            if part_num in video_info["pages"]:
                part_cids[part_num] = video_info["pages"][part_num]["cid"]

        if not part_cids:
            raise ValueError("没有可校验的分P")

        # 4. 抓取线上弹幕
        self.all_online = {}
        failed_parts: list[int] = []
        total = len(part_cids)

        for i, (part_num, cid) in enumerate(part_cids.items(), 1):
            if on_status:
                on_status(f"正在抓取 P{part_num} ({i}/{total})...")

            try:
                online_counter, sender_map = fetch_part(
                    cid=cid,
                    avid=video_info["aid"],
                    sessdata=sessdata,
                    config=self._network_config,
                )
                self.all_online[part_num] = (online_counter, sender_map)
            except RuntimeError as e:
                logger.error(f"P{part_num} 抓取失败: {e}")
                failed_parts.append(part_num)
                if "风控" in str(e):
                    raise

        # 5. 执行校验
        if on_status:
            on_status("正在分析...")

        reports = inspect_all_parts(
            all_expected=self.all_expected,
            all_online=self.all_online,
            config=self._inspection_config,
        )

        # 6. 构建报告
        self.report = InspectionReport(
            bvid=bvid,
            title=video_info["title"],
            total_parts=len(reports),
            reports=reports,
            timestamp=datetime.now().isoformat(),
        )

        return self.report
