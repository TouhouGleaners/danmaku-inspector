"""应用元数据。

定义应用名称、版本、路径等元信息。
"""
from pathlib import Path

from platformdirs import user_data_dir

from danmaku_inspector._version import __version__


# 应用数据目录（import 时计算，运行时不变）
_DATA_DIR = Path(user_data_dir("DanmakuInspector", "Miku_oso"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)


class AppInfo:
    """存放应用元数据。"""
    NAME = "弹幕校验工具"
    NAME_EN = "DanmakuInspector"
    VERSION = __version__

    class Paths:
        """所有应用路径的集中定义。"""
        DATA = _DATA_DIR
        CONFIG = _DATA_DIR / "config.json"
        ACCOUNTS = _DATA_DIR / "accounts.json"
