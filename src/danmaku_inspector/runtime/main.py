"""应用入口。"""
import os
import sys
from pathlib import Path

os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from danmaku_inspector.ui.backend import Backend
from danmaku_inspector.runtime.log_utils import init_app_logging


def main() -> None:
    """启动应用。"""
    init_app_logging()

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    # 注册后端对象
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)

    # 加载 QML
    qml_file = Path(__file__).parent.parent / "ui" / "main.qml"
    engine.load(qml_file)

    if not engine.rootObjects():
        print("QML 加载失败")
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
