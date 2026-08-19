"""Python ↔ QML 桥接层。

把 core 模块的功能暴露给 QML 调用。
"""
import csv
import json
import logging
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Slot, Signal, Property, QAbstractListModel, QModelIndex, Qt

from .core.models import DanmakuFingerprint, PartReport, PartStatus, SenderAnomaly
from .core.parser import parse_all_parts
from .core.fetcher import get_video_info, fetch_part
from .core.inspector import inspect_all_parts

logger = logging.getLogger(__name__)


class ResultModel(QAbstractListModel):
    """校验结果数据模型，暴露给 QML 的 ListView。"""

    # 角色定义
    PART_NUM = Qt.ItemDataRole.UserRole + 1
    STATUS = Qt.ItemDataRole.UserRole + 2
    STATUS_TEXT = Qt.ItemDataRole.UserRole + 3
    ONLINE_COUNT = Qt.ItemDataRole.UserRole + 4
    EXPECTED_COUNT = Qt.ItemDataRole.UserRole + 5
    EXTRA_COUNT = Qt.ItemDataRole.UserRole + 6
    MISMATCH_COUNT = Qt.ItemDataRole.UserRole + 7
    UNSENT_COUNT = Qt.ItemDataRole.UserRole + 8
    UNSENT_RATE = Qt.ItemDataRole.UserRole + 9
    SOURCE_PART = Qt.ItemDataRole.UserRole + 10
    MATCH_RATE = Qt.ItemDataRole.UserRole + 11

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._data: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._data):
            return None

        item = self._data[index.row()]
        role_map = {
            self.PART_NUM: item["part_num"],
            self.STATUS: item["status"],
            self.STATUS_TEXT: item["status_text"],
            self.ONLINE_COUNT: item["online_count"],
            self.EXPECTED_COUNT: item["expected_count"],
            self.EXTRA_COUNT: item["extra_count"],
            self.MISMATCH_COUNT: item["mismatch_count"],
            self.UNSENT_COUNT: item["unsent_count"],
            self.UNSENT_RATE: item["unsent_rate"],
            self.SOURCE_PART: item["source_part"],
            self.MATCH_RATE: item["match_rate"],
        }
        return role_map.get(role)

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.PART_NUM: b"partNum",
            self.STATUS: b"status",
            self.STATUS_TEXT: b"statusText",
            self.ONLINE_COUNT: b"onlineCount",
            self.EXPECTED_COUNT: b"expectedCount",
            self.EXTRA_COUNT: b"extraCount",
            self.MISMATCH_COUNT: b"mismatchCount",
            self.UNSENT_COUNT: b"unsentCount",
            self.UNSENT_RATE: b"unsentRate",
            self.SOURCE_PART: b"sourcePart",
            self.MATCH_RATE: b"matchRate",
        }

    def set_results(self, reports: list[PartReport]) -> None:
        """设置校验结果。"""
        self.beginResetModel()
        self._data = []
        for r in reports:
            status_text = {
                PartStatus.PASS: "通过",
                PartStatus.EXTRA: "错发",
                PartStatus.UNSENT: "漏发",
                PartStatus.BOTH: "错发+漏发",
            }.get(r.status, r.status)

            # 取第一个异常的来源分P和匹配率
            source_part = "-"
            match_rate = "-"
            mismatch_count = 0
            if r.anomalies:
                source_part = f"P{r.anomalies[0].likely_source_part}"
                match_rate = f"{r.anomalies[0].match_rate:.0%}"
                mismatch_count = sum(a.extra_count for a in r.anomalies)

            self._data.append({
                "part_num": f"P{r.part_num}",
                "status": r.status.value,
                "status_text": status_text,
                "online_count": r.online_count,
                "expected_count": r.expected_count,
                "extra_count": r.extra_count,
                "mismatch_count": mismatch_count,
                "unsent_count": r.unsent_count,
                "unsent_rate": f"{r.unsent_rate:.1%}",
                "source_part": source_part,
                "match_rate": match_rate,
            })
        self.endResetModel()

    @Slot(int, result=dict)
    def get_part_detail(self, index: int) -> dict[str, Any]:
        """获取单个分P的详情。"""
        if 0 <= index < len(self._data):
            return self._data[index]
        return {}


class AnomalyModel(QAbstractListModel):
    """异常发送者数据模型。"""

    MIDHASH = Qt.ItemDataRole.UserRole + 1
    EXTRA_COUNT = Qt.ItemDataRole.UserRole + 2
    SOURCE_PART = Qt.ItemDataRole.UserRole + 3
    MATCH_RATE = Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._data: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._data):
            return None

        item = self._data[index.row()]
        role_map = {
            self.MIDHASH: item["midhash"],
            self.EXTRA_COUNT: item["extra_count"],
            self.SOURCE_PART: item["source_part"],
            self.MATCH_RATE: item["match_rate"],
        }
        return role_map.get(role)

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.MIDHASH: b"midhash",
            self.EXTRA_COUNT: b"extraCount",
            self.SOURCE_PART: b"sourcePart",
            self.MATCH_RATE: b"matchRate",
        }

    def set_anomalies(self, anomalies: list[SenderAnomaly]) -> None:
        """设置异常列表。"""
        self.beginResetModel()
        self._data = [
            {
                "midhash": a.midhash,
                "extra_count": a.extra_count,
                "source_part": f"P{a.likely_source_part}",
                "match_rate": f"{a.match_rate:.0%}",
            }
            for a in anomalies
        ]
        self.endResetModel()


class Backend(QObject):
    """后端桥接类，暴露给 QML。"""

    # 信号
    isRunningChanged = Signal()
    statusChanged = Signal()
    errorOccurred = Signal(str)
    _updateResults = Signal()  # 内部信号，用于主线程更新 model

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._is_running: bool = False
        self._status: str = "就绪"
        self._result_model: ResultModel = ResultModel(self)
        self._anomaly_model: AnomalyModel = AnomalyModel(self)
        self._reports: list[PartReport] = []
        self._pending_reports: list[PartReport] | None = None
        self._pending_anomalies: list[SenderAnomaly] | None = None
        self._all_expected: dict[int, Counter[DanmakuFingerprint]] = {}
        self._all_online: dict[int, tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]] = {}
        self._xml_dir: str = ""
        self._updateResults.connect(self._do_update_results)

    @Property(bool, notify=isRunningChanged)
    def isRunning(self) -> bool:
        return self._is_running

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(QObject, constant=True)
    def resultModel(self) -> ResultModel:
        return self._result_model

    @Property(QObject, constant=True)
    def anomalyModel(self) -> AnomalyModel:
        return self._anomaly_model

    @Slot(str, str, str)
    def start_inspect(self, bvid: str, cookie: str, xml_dir: str) -> None:
        """开始校验（在子线程中运行）。"""
        if self._is_running:
            return

        logger.info(f"开始检测: bvid={bvid}, xml_dir={xml_dir}")
        thread = threading.Thread(target=self._run_inspect, args=(bvid, cookie, xml_dir))
        thread.daemon = True
        thread.start()
        logger.info("线程已启动")

    def _run_inspect(self, bvid: str, cookie: str, xml_dir: str) -> None:
        """实际的校验逻辑。"""
        self._xml_dir = xml_dir
        self._is_running = True
        self.isRunningChanged.emit()
        self._status = "正在解析本地文件..."
        self.statusChanged.emit()

        try:
            # 1. 解析本地 XML
            xml_path = Path(xml_dir)
            logger.info(f"解析目录: {xml_path}")
            logger.info(f"目录存在: {xml_path.exists()}")
            all_expected = parse_all_parts(xml_path)
            if not all_expected:
                raise ValueError("未找到任何 XML 文件")

            self._status = "正在获取视频信息..."
            self.statusChanged.emit()

            # 2. 获取视频信息
            video_info = get_video_info(bvid, cookie)

            # 3. 构建 cid 映射
            part_cids: dict[int, int] = {}
            for part_num in all_expected.keys():
                if part_num in video_info["pages"]:
                    part_cids[part_num] = video_info["pages"][part_num]["cid"]

            if not part_cids:
                raise ValueError("没有可校验的分P")

            self._status = f"正在抓取弹幕 (0/{len(part_cids)})..."
            self.statusChanged.emit()

            # 4. 抓取线上弹幕
            self._all_online = {}
            failed_parts: list[int] = []
            for i, (part_num, cid) in enumerate(part_cids.items(), 1):
                self._status = f"正在抓取 P{part_num} ({i}/{len(part_cids)})..."
                self.statusChanged.emit()

                try:
                    online_counter, sender_map = fetch_part(
                        cid=cid,
                        avid=video_info["aid"],
                        cookie=cookie,
                    )
                    self._all_online[part_num] = (online_counter, sender_map)
                except RuntimeError as e:
                    logger.error(f"P{part_num} 抓取失败: {e}")
                    failed_parts.append(part_num)
                    # 被风控了，停止抓取
                    if "风控" in str(e):
                        self._status = f"被B站风控了，已抓取 {i}/{len(part_cids)} 个分P"
                        self.statusChanged.emit()
                        break

            self._status = "正在分析..."
            self.statusChanged.emit()

            # 5. 执行校验
            self._all_expected = all_expected
            self._reports = inspect_all_parts(
                all_expected=all_expected,
                all_online=self._all_online,
            )

            # 6. 更新模型（通过信号切回主线程）
            logger.info(f"设置结果，共 {len(self._reports)} 条")
            self._pending_reports = self._reports
            for r in self._reports:
                if r.anomalies:
                    self._pending_anomalies = r.anomalies
                    break
            self._updateResults.emit()

            # 显示警告
            if failed_parts:
                self._status = f"完成，但 {len(failed_parts)} 个分P抓取失败: P{', P'.join(map(str, failed_parts))}"
            else:
                self._status = f"完成，共 {len(self._reports)} 个分P"
            self.statusChanged.emit()

        except Exception as e:
            logger.error(f"校验失败: {e}")
            self._status = f"错误: {e}"
            self.statusChanged.emit()
            self.errorOccurred.emit(str(e))

        finally:
            self._is_running = False
            self.isRunningChanged.emit()

    @Slot()
    def _do_update_results(self) -> None:
        """在主线程里更新 model。"""
        if self._pending_reports:
            self._result_model.set_results(self._pending_reports)
            logger.info(f"模型行数: {self._result_model.rowCount()}")
            self._pending_reports = None
        if self._pending_anomalies:
            self._anomaly_model.set_anomalies(self._pending_anomalies)
            self._pending_anomalies = None

    @Slot(int)
    def show_part_detail(self, index: int) -> None:
        """显示指定分P的详情。"""
        if 0 <= index < len(self._reports):
            report = self._reports[index]
            self._anomaly_model.set_anomalies(report.anomalies)

    @Slot(int)
    def export_part_csv(self, part_index: int) -> None:
        """导出单个分P的 CSV。"""
        if not self._reports or part_index < 0 or part_index >= len(self._reports):
            return

        report = self._reports[part_index]
        output_path = Path(self._xml_dir) / "export"
        output_path.mkdir(parents=True, exist_ok=True)

        csv_file = output_path / f"P{report.part_num}.csv"

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
        self._status = f"已导出: {csv_file.name}"
        self.statusChanged.emit()

    @Slot(int)
    def export_part_diff(self, part_index: int) -> None:
        """导出单个分P的差集: Expected - Online = 漏发。"""
        if not self._reports or part_index < 0 or part_index >= len(self._reports):
            return

        report = self._reports[part_index]
        output_path = Path(self._xml_dir) / "export"
        output_path.mkdir(parents=True, exist_ok=True)

        diff_file = output_path / f"P{report.part_num}_Expected-Online.xml"
        self._generate_diff_xml(report.part_num, diff_file)
        logger.info(f"导出: {diff_file.name}")
        self._status = f"已导出: {diff_file.name}"
        self.statusChanged.emit()

    @Slot(int)
    def export_part_danmaku_csv(self, part_index: int) -> None:
        """导出单个分P的全量弹幕 CSV（按 BiliDanmakuDownloader 格式）。"""
        if not self._all_online or part_index < 0 or part_index >= len(self._reports):
            return

        report = self._reports[part_index]
        part_num = report.part_num

        if part_num not in self._all_online:
            return

        online_counter, _ = self._all_online[part_num]
        output_path = Path(self._xml_dir) / "export"
        output_path.mkdir(parents=True, exist_ok=True)

        csv_file = output_path / f"P{part_num}_All_Danmaku.csv"

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
        self._status = f"已导出: {csv_file.name}"
        self.statusChanged.emit()

    @Slot(int)
    def export_part_danmaku_xml(self, part_index: int) -> None:
        """导出单个分P的全量弹幕 XML（按 progress 升序）。"""
        if not self._all_online or part_index < 0 or part_index >= len(self._reports):
            return

        report = self._reports[part_index]
        part_num = report.part_num

        if part_num not in self._all_online:
            return

        online_counter, _ = self._all_online[part_num]
        output_path = Path(self._xml_dir) / "export"
        output_path.mkdir(parents=True, exist_ok=True)

        xml_file = output_path / f"P{part_num}_All_Danmaku.xml"

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
        self._status = f"已导出: {xml_file.name}"
        self.statusChanged.emit()

    @Slot()
    def export_csv(self) -> None:
        """导出全部分P的 CSV。"""
        if not self._reports:
            return

        output_path = Path(self._xml_dir) / "export"
        output_path.mkdir(parents=True, exist_ok=True)

        csv_file = output_path / "report.csv"

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
        self._status = f"已导出: {csv_file.name}"
        self.statusChanged.emit()

    @Slot(str, float)
    def export_diff(self, output_dir: str, threshold: float) -> None:
        """导出漏发弹幕为 Diff.xml。

        Args:
            output_dir: 输出目录
            threshold: 漏发比例阈值 (0-1)
        """
        if not self._reports or not self._all_expected:
            return

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        exported = 0
        for report in self._reports:
            # 计算漏发比例
            if report.expected_count == 0:
                continue
            unsent_rate = report.unsent_count / report.expected_count

            # 只导出漏发比例大于阈值的
            if unsent_rate >= threshold and report.unsent_count > 0:
                # 生成差集文件: Expected - Online = 漏发
                diff_file = output_path / f"P{report.part_num}_Expected-Online.xml"
                self._generate_diff_xml(report.part_num, diff_file)
                logger.info(f"导出: {diff_file.name} (漏发 {report.unsent_count} 条, 比例 {unsent_rate:.1%})")
                exported += 1

        self._status = f"导出完成，共 {exported} 个文件"
        self.statusChanged.emit()

    def _generate_diff_xml(self, part_num: int, output_path: Path) -> None:
        """生成单个分P的 Diff.xml。"""
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
                # 还原为 XML 格式
                progress_sec = fp.progress_ms / 1000.0
                p_attr = f"{progress_sec:.5f},{fp.mode},{fp.fontsize},{fp.color},0,0,diff,0,1"
                elem = ET.SubElement(root, "d", p=p_attr)
                elem.text = fp.content

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
