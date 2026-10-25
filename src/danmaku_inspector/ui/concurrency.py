"""Qt 侧并发原语。

把阻塞函数包装为 QThreadPool 任务，执行完毕经 Qt 信号回传结果与异常。
本模块位于 UI 边界，仅由 Qt 侧调用。
"""
import logging
import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class PoolTaskSignals(QObject):
    """任务信号载体。

    Attributes:
        result (Signal): 成功信号，携带返回值。
        error (Signal): 失败信号，携带异常对象。
        finished (Signal): 结束信号，无论成败均触发。
    """
    result = Signal(object)
    error = Signal(object)
    finished = Signal()


class PoolTask(QRunnable):
    """一次性线程池任务包装器。

    执行完毕后自动从保活注册表移除。
    """

    _keep_alive_registry: set["PoolTask"] = set()
    _registry_lock = threading.Lock()

    def __init__(self, fn: Callable, *args, **kwargs) -> None:
        """包装待执行函数。

        Args:
            fn (Callable): 阻塞的业务函数。
            *args: 传给 fn 的位置参数。
            **kwargs: 传给 fn 的关键字参数。
        """
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = PoolTaskSignals()

        self.setAutoDelete(False)

        with PoolTask._registry_lock:
            PoolTask._keep_alive_registry.add(self)

    def run(self) -> None:
        """执行被包装的函数，并将结果或异常经信号发出。"""
        threading.current_thread().name = "PoolThread"
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            logger.error(f"后台任务执行异常: {e}\n{traceback.format_exc()}")
            self.signals.error.emit(e)
        finally:
            self.signals.finished.emit()
            with PoolTask._registry_lock:
                PoolTask._keep_alive_registry.discard(self)

    @classmethod
    def submit(cls, fn: Callable, on_result: Callable, on_error: Callable, *args, **kwargs) -> "PoolTask":
        """将阻塞函数提交到全局线程池。

        on_result 与 on_error 若是主线程 QObject 的方法，Qt 会自动排队到主线程执行。

        Args:
            fn (Callable): 阻塞的业务函数。
            on_result (Callable): 成功回调，接收 fn 的返回值。
            on_error (Callable): 失败回调，接收异常对象。
            *args: 传给 fn 的位置参数。
            **kwargs: 传给 fn 的关键字参数。

        Returns:
            PoolTask: 已提交的任务对象。
        """
        task = cls(fn, *args, **kwargs)
        task.signals.result.connect(on_result)
        task.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(task)
        return task
