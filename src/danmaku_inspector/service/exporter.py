"""导出服务。

负责所有导出逻辑（CSV、XML、Diff），不依赖 Qt。
"""
import csv
import logging
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

from danmaku_inspector.types.models import DanmakuFingerprint, PartReport

logger = logging.getLogger(__name__)


class ExportService:
    """导出服务。

    负责所有导出逻辑，不依赖 Qt。
    """

    def __init__(
        self,
        reports: list[PartReport],
        all_expected: dict[int, Counter[DanmakuFingerprint]],
        all_online: dict[int, tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]],
        output_dir: str,
    ) -> None:
        """初始化导出服务。

        Args:
            reports: 各分P的检测报告列表。
            all_expected: 本地应发弹幕 {part_num: Counter}。
            all_online: 线上弹幕 {part_num: (Counter, sender_map)}。
            output_dir: 输出目录。
        """
        self._reports = reports
        self._all_expected = all_expected
        self._all_online = all_online
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export_report_csv(self) -> Path:
        """导出全部分P的报告 CSV。

        Returns:
            导出文件路径。
        """
        csv_file = self._output_dir / "report.csv"

        with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["分P", "状态", "线上", "应发", "多余", "错发", "漏发", "漏发率"])
            for report in self._reports:
                writer.writerow([
                    report.part_num,
                    report.status.value,
                    report.online_count,
                    report.expected_count,
                    report.extra_count,
                    sum(a.extra_count for a in report.anomalies),
                    report.unsent_count,
                    f"{report.unsent_rate:.1%}",
                ])

        logger.info(f"导出: {csv_file.name}")
        return csv_file

    def export_part_csv(self, part_index: int) -> Path | None:
        """导出单个分P的报告 CSV。

        Args:
            part_index: 分P索引。

        Returns:
            导出文件路径，无效索引返回 None。
        """
        if part_index < 0 or part_index >= len(self._reports):
            return None

        report = self._reports[part_index]
        csv_file = self._output_dir / f"P{report.part_num}.csv"

        with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["分P", "状态", "线上", "应发", "多余", "错发", "漏发", "漏发率"])
            writer.writerow([
                report.part_num,
                report.status.value,
                report.online_count,
                report.expected_count,
                report.extra_count,
                sum(a.extra_count for a in report.anomalies),
                report.unsent_count,
                f"{report.unsent_rate:.1%}",
            ])

        logger.info(f"导出: {csv_file.name}")
        return csv_file

    def export_part_diff(self, part_index: int) -> Path | None:
        """导出单个分P的差集: Expected - Online = 漏发。

        Args:
            part_index: 分P索引。

        Returns:
            导出文件路径，无效索引返回 None。
        """
        if part_index < 0 or part_index >= len(self._reports):
            return None

        report = self._reports[part_index]
        xml_file = self._output_dir / f"P{report.part_num}_Expected-Online.xml"
        self._generate_diff_xml(report.part_num, xml_file)
        logger.info(f"导出: {xml_file.name}")
        return xml_file

    def export_part_danmaku_csv(self, part_index: int) -> Path | None:
        """导出单个分P的全量弹幕 CSV（按 BiliDanmakuDownloader 格式）。

        Args:
            part_index: 分P索引。

        Returns:
            导出文件路径，无效索引返回 None。
        """
        if part_index < 0 or part_index >= len(self._reports):
            return None

        report = self._reports[part_index]
        part_num = report.part_num

        if part_num not in self._all_online:
            return None

        online_counter, _ = self._all_online[part_num]
        csv_file = self._output_dir / f"P{part_num}_All_Danmaku.csv"

        # 按 progress 排序
        sorted_items = sorted(online_counter.items(), key=lambda x: x[0].progress_ms)

        with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            # 元数据
            writer.writerow(["分P序号", part_num])
            writer.writerow(["弹幕总数", sum(online_counter.values())])
            writer.writerow(["导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
            writer.writerow([])
            # 列标题
            writer.writerow(["出现时间(毫秒)", "模式", "字体大小", "颜色", "内容", "数量"])
            # 数据行
            for fp, count in sorted_items:
                color_hex = f"#{fp.color:06x}"
                writer.writerow([fp.progress_ms, fp.mode, fp.fontsize, color_hex, fp.content, count])

        logger.info(f"导出: {csv_file.name}")
        return csv_file

    def export_part_danmaku_xml(self, part_index: int) -> Path | None:
        """导出单个分P的全量弹幕 XML（按 progress 升序）。

        Args:
            part_index: 分P索引。

        Returns:
            导出文件路径，无效索引返回 None。
        """
        if part_index < 0 or part_index >= len(self._reports):
            return None

        report = self._reports[part_index]
        part_num = report.part_num

        if part_num not in self._all_online:
            return None

        online_counter, _ = self._all_online[part_num]
        xml_file = self._output_dir / f"P{part_num}_All_Danmaku.xml"

        # 按 progress 排序
        sorted_items = sorted(online_counter.items(), key=lambda x: x[0].progress_ms)

        # 生成 XML
        root = ET.Element("i")
        for fp, count in sorted_items:
            for _ in range(count):
                progress_sec = fp.progress_ms / 1000.0
                p_attr = f"{progress_sec:.5f},{fp.mode},{fp.fontsize},{fp.color},0,0,online,0,1"
                elem = ET.SubElement(root, "d", p=p_attr)
                elem.text = fp.content

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(xml_file, encoding="utf-8", xml_declaration=True)

        logger.info(f"导出: {xml_file.name}")
        return xml_file

    def export_diff_batch(self, threshold: float) -> list[Path]:
        """批量导出漏发弹幕为 Diff.xml。

        Args:
            threshold: 漏发比例阈值 (0-1)。

        Returns:
            导出文件路径列表。
        """
        exported = []
        for report in self._reports:
            if report.expected_count == 0:
                continue
            unsent_rate = report.unsent_count / report.expected_count

            if unsent_rate >= threshold and report.unsent_count > 0:
                xml_file = self._output_dir / f"P{report.part_num}_Expected-Online.xml"
                self._generate_diff_xml(report.part_num, xml_file)
                logger.info(f"导出: {xml_file.name} (漏发 {report.unsent_count} 条, 比例 {unsent_rate:.1%})")
                exported.append(xml_file)

        return exported

    def _generate_diff_xml(self, part_num: int, output_path: Path) -> None:
        """生成单个分P的 Diff.xml。

        Args:
            part_num: 分P编号。
            output_path: 输出文件路径。
        """
        if part_num not in self._all_expected or part_num not in self._all_online:
            return

        expected = self._all_expected[part_num]
        online, _ = self._all_online[part_num]

        # 计算漏发 = Expected - All
        unsent = expected - online

        # 生成 XML
        root = ET.Element("i")
        for fp, count in unsent.items():
            for _ in range(count):
                progress_sec = fp.progress_ms / 1000.0
                p_attr = f"{progress_sec:.5f},{fp.mode},{fp.fontsize},{fp.color},0,0,diff,0,1"
                elem = ET.SubElement(root, "d", p=p_attr)
                elem.text = fp.content

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
