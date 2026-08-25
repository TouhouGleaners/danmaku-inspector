"""Python ↔ QML 桥接层。

把各层模块的功能暴露给 QML 调用。
"""
import logging
import threading
from typing import Any, Callable
from pathlib import Path


def _mask(value: str) -> str:
    """遮蔽凭据：保留前4后4，中间用 * 替代，总长不超过 20。"""
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 8:
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
    stars = min(len(value) - 8, 8)
    return f"{value[:4]}{'*' * stars}{value[-4:]}"

from PySide6.QtCore import QObject, Slot, Signal, Property, QAbstractListModel, QModelIndex, Qt

from danmaku_inspector.types.models import PartReport, PartStatus, SenderAnomaly, InspectionReport, AccountCredential
from danmaku_inspector.service.orchestrator import InspectionOrchestrator
from danmaku_inspector.service.exporter import ExportService
from danmaku_inspector.runtime.config_manager import ConfigManager
from danmaku_inspector.runtime.credential_manager import CredentialManager

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
        """初始化 ResultModel。

        Args:
            parent: 父对象。
        """
        super().__init__(parent)
        self._data: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回行数。

        Args:
            parent: 父索引。

        Returns:
            数据行数。
        """
        return len(self._data)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """返回指定索引和角色的数据。

        Args:
            index: 模型索引。
            role: 数据角色。

        Returns:
            对应角色的数据值，无效索引返回 None。
        """
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
        """返回角色名称映射，供 QML 通过名称访问数据。

        Qt Model/View 架构中，每个单元格可有多种数据（显示文本、图标等），
        通过角色区分。此方法定义自定义角色的名称，QML 可通过名称访问对应字段。

        Returns:
            {角色ID: 角色名称} 映射。
        """
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
        """设置校验结果。

        Args:
            reports: 分P检测报告列表。
        """
        self.beginResetModel()
        self._data = []
        for r in reports:
            status_text = {
                PartStatus.PASS: "通过",
                PartStatus.EXTRA: "错发",
                PartStatus.UNSENT: "漏发",
                PartStatus.BOTH: "错发+漏发",
            }.get(r.status, r.status)

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
        """获取单个分P的详情。

        Args:
            index: 分P索引。

        Returns:
            分P详情字典，无效索引返回空字典。
        """
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
        """初始化 AnomalyModel。

        Args:
            parent: 父对象。
        """
        super().__init__(parent)
        self._data: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回行数。

        Args:
            parent: 父索引。

        Returns:
            数据行数。
        """
        return len(self._data)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """返回指定索引和角色的数据。

        Args:
            index: 模型索引。
            role: 数据角色。

        Returns:
            对应角色的数据值，无效索引返回 None。
        """
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
        """返回角色名称映射，供 QML 通过名称访问数据。

        Returns:
            {角色ID: 角色名称} 映射。
        """
        return {
            self.MIDHASH: b"midhash",
            self.EXTRA_COUNT: b"extraCount",
            self.SOURCE_PART: b"sourcePart",
            self.MATCH_RATE: b"matchRate",
        }

    def set_anomalies(self, anomalies: list[SenderAnomaly]) -> None:
        """设置异常列表。

        Args:
            anomalies: 异常发送者列表。
        """
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
    """后端桥接类，暴露给 QML。

    只做 Qt 桥接，业务逻辑委托给 InspectionOrchestrator 和 ExportService。
    """

    # 信号
    isRunningChanged = Signal(bool)
    statusChanged = Signal(str)
    errorOccurred = Signal(str)
    _inspectFinished = Signal(object)  # 用于子线程回调主线程

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化 Backend。

        Args:
            parent: 父对象。
        """
        super().__init__(parent)
        self._is_running: bool = False
        self._status: str = "就绪"
        self._result_model: ResultModel = ResultModel(self)
        self._anomaly_model: AnomalyModel = AnomalyModel(self)
        self._orchestrator: InspectionOrchestrator | None = None
        self._exporter: ExportService | None = None
        self._xml_dir: str = ""

        # 持久化管理器
        self._config_manager = ConfigManager()
        self._credential_manager = CredentialManager()
        self._app_config = self._config_manager.load()
        self._credentials = self._credential_manager.load_credentials()
        self._active_index: int = 0 if self._credentials else -1

        # 初始化账号模型
        self._refresh_account_model()

        self._inspectFinished.connect(self._on_inspect_finished)

    # region QML 属性

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

    @Property(str, notify=statusChanged)
    def cookie(self) -> str:
        """当前 SESSDATA（遮蔽后）。"""
        if self._active_index >= 0 and self._active_index < len(self._credentials):
            return self._credentials[self._active_index].masked_sessdata
        return ""

    @Property(str, notify=statusChanged)
    def rawCookie(self) -> str:
        """当前 SESSDATA（原始值）。"""
        if self._active_index >= 0 and self._active_index < len(self._credentials):
            return self._credentials[self._active_index].sessdata
        return ""

    @Property(str, constant=True)
    def version(self) -> str:
        from danmaku_inspector._version import __version__
        return __version__

    # endregion

    # region QML 方法

    @Slot(str)
    def save_sessdata(self, sessdata: str) -> None:
        """保存 SESSDATA 到加密存储。"""
        if not sessdata:
            return
        if self._credentials:
            self._credentials[0].sessdata = sessdata
        else:
            self._credentials = [AccountCredential(sessdata=sessdata)]
        self._credential_manager.save_credentials(self._credentials)
        logger.info("SESSDATA 已保存。")

    @Slot(str, int, int, result=list)
    def getFilteredReports(self, status_filter: str, sort_index: int, sort_order: int) -> list[dict]:
        """获取筛选和排序后的报告数据。"""
        if not self._orchestrator or not self._orchestrator.report:
            return []

        reports = self._orchestrator.report.reports

        # 筛选
        if status_filter != "ALL":
            reports = [r for r in reports if r.status.value == status_filter]

        # 排序
        sort_keys: dict[int, Callable[[PartReport], Any]] = {
            0: lambda r: r.part_num,
            1: lambda r: r.unsent_rate,
            2: lambda r: sum(a.extra_count for a in r.anomalies),
            3: lambda r: r.unsent_count,
        }
        sort_fn = sort_keys.get(sort_index, sort_keys[0])
        reports = sorted(reports, key=sort_fn, reverse=sort_order == -1)

        # 转换为字典
        result = []
        for r in reports:
            mismatch_count = sum(a.extra_count for a in r.anomalies)
            source_part = "-"
            match_rate = "-"
            if r.anomalies:
                source_part = f"P{r.anomalies[0].likely_source_part}"
                match_rate = f"{r.anomalies[0].match_rate:.0%}"

            result.append({
                "partNum": f"P{r.part_num}",
                "status": r.status.value,
                "statusText": {
                    PartStatus.PASS: "通过",
                    PartStatus.EXTRA: "错发",
                    PartStatus.UNSENT: "漏发",
                    PartStatus.BOTH: "错发+漏发",
                }.get(r.status, r.status.value),
                "onlineCount": r.online_count,
                "expectedCount": r.expected_count,
                "extraCount": r.extra_count,
                "mismatchCount": mismatch_count,
                "unsentCount": r.unsent_count,
                "unsentRate": f"{r.unsent_rate:.1%}",
                "sourcePart": source_part,
                "matchRate": match_rate,
            })

        return result

    @Slot(str, str, str)
    def start_inspect(self, bvid: str, sessdata: str, xml_dir: str) -> None:
        """开始校验（在子线程中运行）。"""
        if self._is_running:
            return
        self.save_sessdata(sessdata)
        self._xml_dir = xml_dir
        self._is_running = True
        self.isRunningChanged.emit(True)
        logger.info(f"开始检测: bvid={bvid}, xml_dir={xml_dir}")
        thread = threading.Thread(target=self._run_inspect, args=(bvid, sessdata, xml_dir))
        thread.daemon = True
        thread.start()
        logger.info("线程已启动")

    @Slot(int)
    def show_part_detail(self, index: int) -> None:
        """显示指定分P的详情。"""
        if self._orchestrator and self._orchestrator.report and 0 <= index < len(self._orchestrator.report.reports):
            report = self._orchestrator.report.reports[index]
            self._anomaly_model.set_anomalies(report.anomalies)

    @Slot(int)
    def export_part_csv(self, part_index: int) -> None:
        """导出单个分P的 CSV。"""
        if self._exporter:
            path = self._exporter.export_part_csv(part_index)
            if path:
                self._status = f"已导出: {path.name}"
                self.statusChanged.emit(self._status)

    @Slot(int)
    def export_part_diff(self, part_index: int) -> None:
        """导出单个分P的差集。"""
        if self._exporter:
            path = self._exporter.export_part_diff(part_index)
            if path:
                self._status = f"已导出: {path.name}"
                self.statusChanged.emit(self._status)

    @Slot(int)
    def export_part_danmaku_csv(self, part_index: int) -> None:
        """导出单个分P的全量弹幕 CSV。"""
        if self._exporter:
            path = self._exporter.export_part_danmaku_csv(part_index)
            if path:
                self._status = f"已导出: {path.name}"
                self.statusChanged.emit(self._status)

    @Slot(int)
    def export_part_danmaku_xml(self, part_index: int) -> None:
        """导出单个分P的全量弹幕 XML。"""
        if self._exporter:
            path = self._exporter.export_part_danmaku_xml(part_index)
            if path:
                self._status = f"已导出: {path.name}"
                self.statusChanged.emit(self._status)

    @Slot()
    def export_csv(self) -> None:
        """导出全部分P的 CSV。"""
        if self._exporter:
            path = self._exporter.export_report_csv()
            self._status = f"已导出: {path.name}"
            self.statusChanged.emit(self._status)

    @Slot(str)
    def export_diff(self, output_dir: str) -> None:
        """批量导出漏发弹幕。"""
        if self._exporter and self._orchestrator:
            self._exporter.set_output_dir(output_dir)
            threshold = self._orchestrator._inspection_config.unsent_rate_threshold
            exported = self._exporter.export_diff_batch(threshold)
            self._status = f"导出完成，共 {len(exported)} 个文件"
            self.statusChanged.emit(self._status)

    @Slot(int, result=dict)
    def getAccount(self, index: int) -> dict:
        """获取账号信息。"""
        if 0 <= index < len(self._credentials):
            acc = self._credentials[index]
            return {
                "uid": str(acc.uid),
                "name": acc.name,
                "maskedSessdata": acc.masked_sessdata,
                "sessdata": acc.sessdata,
                "level": acc.level,
                "isValid": acc.is_valid or False,
                "isActive": index == self._active_index,
            }
        return {}

    @Slot(int, result=int)
    def getAccountCount(self) -> int:
        return len(self._credentials)

    @Slot(str)
    def addAccount(self, sessdata: str) -> None:
        """添加账号。"""
        if not sessdata:
            return
        for acc in self._credentials:
            if acc.sessdata == sessdata:
                logger.warning("SESSDATA 已存在，跳过添加。")
                return
        acc = AccountCredential(sessdata=sessdata)
        self._credentials.append(acc)
        if len(self._credentials) == 1:
            self._active_index = 0
        self._credential_manager.save_credentials(self._credentials)
        self._refresh_account_model()
        self.statusChanged.emit(self._status)
        logger.info(f"已添加账号，共 {len(self._credentials)} 个。")

    @Slot(int, str)
    def editAccount(self, index: int, sessdata: str) -> None:
        """编辑账号。"""
        if not (0 <= index < len(self._credentials) and sessdata):
            return
        for i, acc in enumerate(self._credentials):
            if i != index and acc.sessdata == sessdata:
                logger.warning("SESSDATA 已存在，跳过编辑。")
                return
        self._credentials[index].sessdata = sessdata
        self._credentials[index].is_valid = None
        self._credential_manager.save_credentials(self._credentials)
        self._refresh_account_model()
        self.statusChanged.emit(self._status)
        logger.info(f"已编辑账号 {index}。")

    @Slot(int)
    def deleteAccount(self, index: int) -> None:
        """删除账号。"""
        if not (0 <= index < len(self._credentials)):
            return
        self._credentials.pop(index)
        if self._active_index >= len(self._credentials):
            self._active_index = len(self._credentials) - 1
        self._credential_manager.save_credentials(self._credentials)
        self._refresh_account_model()
        self.statusChanged.emit(self._status)
        logger.info(f"已删除账号，剩余 {len(self._credentials)} 个。")

    @Slot(int)
    def useAccount(self, index: int) -> None:
        """切换到指定账号。"""
        if 0 <= index < len(self._credentials):
            self._active_index = index
            self._refresh_account_model()
            self.statusChanged.emit(self._status)
            logger.info(f"已切换到账号 {index}。")

    @Slot(int)
    def checkAccount(self, index: int) -> None:
        """检测账号是否有效。"""
        if not (0 <= index < len(self._credentials)):
            return
        acc = self._credentials[index]
        logger.info(f"正在检测账号 {index}...")
        try:
            from danmaku_inspector.repo.bilibili.fetcher import check_account, get_user_info
            is_valid = check_account(acc.sessdata, self._app_config.network)
            acc.is_valid = is_valid
            if is_valid:
                try:
                    user_info = get_user_info(acc.sessdata, self._app_config.network)
                    acc.uid = user_info.get("mid", 0)
                    acc.name = user_info.get("uname", "")
                    acc.level = user_info.get("level_info", {}).get("current_level", -1)
                except Exception as e:
                    logger.warning(f"获取用户信息失败: {e}")
            self._credential_manager.save_credentials(self._credentials)
            self._refresh_account_model()
            self.statusChanged.emit(self._status)
            logger.info(f"账号 {index} 检测结果: {'有效' if is_valid else '失效'}")
        except Exception as e:
            logger.error(f"账号 {index} 检测失败: {e}")
            acc.is_valid = False
            self._refresh_account_model()
            self.statusChanged.emit(self._status)

    # endregion

    # region 内部方法

    def _refresh_account_model(self) -> None:
        """刷新账号数据模型。"""
        accounts = []
        for i, acc in enumerate(self._credentials):
            accounts.append({
                "uid": str(acc.uid),
                "name": acc.name,
                "maskedSessdata": acc.masked_sessdata,
                "sessdata": acc.sessdata,
                "level": acc.level,
                "isValid": acc.is_valid or False,
                "isActive": i == self._active_index,
            })
        self._account_model.set_accounts(accounts) if hasattr(self, '_account_model') else None

    def _run_inspect(self, bvid: str, sessdata: str, xml_dir: str) -> None:
        """实际的校验逻辑（在子线程中运行）。"""
        try:
            self._orchestrator = InspectionOrchestrator(
                inspection_config=self._app_config.inspection,
                network_config=self._app_config.network,
            )
            report = self._orchestrator.run(
                bvid=bvid,
                sessdata=sessdata,
                xml_dir=xml_dir,
                on_status=lambda s: self.statusChanged.emit(s),
            )

            # 初始化导出服务
            self._exporter = ExportService(
                reports=report.reports,
                all_expected=self._orchestrator.all_expected,
                all_online=self._orchestrator.all_online,
                output_dir=str(Path(xml_dir) / "export"),
            )

            # 通过信号回传结果
            self._inspectFinished.emit(report)

        except RuntimeError as e:
            if "风控" in str(e):
                self.statusChanged.emit(f"被B站风控了: {e}")
            else:
                self.statusChanged.emit(f"错误: {e}")
            self.errorOccurred.emit(str(e))

        except Exception as e:
            logger.error(f"校验失败: {e}")
            self.statusChanged.emit(f"错误: {e}")
            self.errorOccurred.emit(str(e))

        finally:
            self._is_running = False
            self.isRunningChanged.emit(False)

    @Slot(InspectionReport)
    def _on_inspect_finished(self, report: InspectionReport) -> None:
        """校验完成回调（主线程）。"""
        self._result_model.set_results(report.reports)
        for r in report.reports:
            if r.anomalies:
                self._anomaly_model.set_anomalies(r.anomalies)
                break
        self._status = f"完成，共 {report.total_parts} 个分P"
        self.statusChanged.emit(self._status)

    # endregion
