"""应用入口。"""
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from danmaku_inspector.ui.backend import Backend
from danmaku_inspector.runtime.log_utils import init_app_logging


def main() -> None:
    """启动应用。"""
    init_app_logging()

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    # 注册后端对象（保持引用，防止被 GC）
    backend = Backend()
    app.setProperty("backend", backend)  # 绑定到 app 生命周期
    engine.rootContext().setContextProperty("backend", backend)

    # 加载 QML
    qml_file = Path(__file__).parent / "ui" / "main.qml"
    engine.load(qml_file)

    if not engine.rootObjects():
        print("QML 加载失败")
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
