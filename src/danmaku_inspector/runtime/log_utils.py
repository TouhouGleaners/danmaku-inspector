"""日志工具。

提供统一的日志初始化。
"""
import sys
import logging


def init_app_logging(level: int = logging.DEBUG) -> None:
    """初始化全局日志系统。

    Args:
        level: 日志级别。
    """
    formatter = logging.Formatter(
        '[%(asctime)s] [%(threadName)s/%(levelname)s] [%(name)s]: %(message)s',
        datefmt='%H:%M:%S'
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    # 屏蔽第三方库的噪音
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logging.info("日志系统初始化完成。")
