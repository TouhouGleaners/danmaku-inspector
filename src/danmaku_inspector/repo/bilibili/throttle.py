"""抓取调度原语。

提供限流（令牌桶）与熔断（Circuit Breaker），供并发抓取任务共享。
"""
import threading
import time


class CrawlAborted(Exception):
    """熔断已触发，抓取中止。"""


class TokenBucket:
    """令牌桶限流器（Token Bucket）。

    以恒定速率补充令牌，acquire 阻塞至取到令牌。
    """

    def __init__(self, rate: float, burst: int) -> None:
        """初始化令牌桶。

        Args:
            rate (float): 每秒补充的令牌数。
            burst (int): 桶容量，即可连续发出的请求数。

        Raises:
            ValueError: rate 非正数，或 burst 小于 1。
        """
        if rate <= 0:
            raise ValueError(f"rate 必须为正数，收到 {rate}")
        if burst < 1:
            raise ValueError(f"burst 至少为 1，收到 {burst}")

        self._rate = float(rate)
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """取一个令牌，必要时阻塞。"""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


class CircuitBreaker:
    """熔断器（Circuit Breaker）。

    熔断后所有 guard 调用抛出 CrawlAborted，不再发出请求。
    熔断单向，不可恢复。
    """

    def __init__(self) -> None:
        self._tripped = False
        self._reason = ""
        self._lock = threading.Lock()

    def trip(self, reason: str) -> None:
        """触发熔断，仅记录首次原因。

        Args:
            reason (str): 熔断原因。
        """
        with self._lock:
            if not self._tripped:
                self._tripped = True
                self._reason = reason

    def guard(self) -> None:
        """已熔断则抛出 CrawlAborted。

        Raises:
            CrawlAborted: 熔断已触发。
        """
        with self._lock:
            if self._tripped:
                raise CrawlAborted(self._reason or "抓取已中止")

    @property
    def tripped(self) -> bool:
        """是否已触发熔断。"""
        with self._lock:
            return self._tripped

    @property
    def reason(self) -> str:
        """熔断原因，未触发时为空字符串。"""
        with self._lock:
            return self._reason


class CrawlThrottle:
    """限流与熔断的组合门。

    一次 run 内的所有请求共享同一个实例。
    """

    def __init__(self, rate_per_second: float, burst: int) -> None:
        """初始化组合门。

        Args:
            rate_per_second (float): 全局请求速率上限（个/秒）。
            burst (int): 令牌桶突发容量。
        """
        self._bucket = TokenBucket(rate_per_second, burst)
        self._breaker = CircuitBreaker()

    def wait(self) -> None:
        """等待至可发出一个请求。

        顺序为：确认未熔断、等待令牌、复查熔断状态。

        Raises:
            CrawlAborted: 已熔断，或等待令牌期间被熔断。
        """
        self._breaker.guard()
        self._bucket.acquire()
        self._breaker.guard()

    def trip(self, reason: str) -> None:
        """触发熔断，停止后续抓取。

        Args:
            reason (str): 熔断原因。
        """
        self._breaker.trip(reason)

    @property
    def tripped(self) -> bool:
        """是否已触发熔断。"""
        return self._breaker.tripped

    @property
    def reason(self) -> str:
        """熔断原因。"""
        return self._breaker.reason
