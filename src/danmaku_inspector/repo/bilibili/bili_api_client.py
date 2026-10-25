"""B站 API 客户端。

发送单次 HTTP 请求并解析响应，输出结构化结果或抛出分型异常。
重试、限流、续传等调度不在此层。
"""
import json
import logging
import zlib
from contextlib import contextmanager
from typing import Any, Generator

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from ..protobuf import dm_pb2 as danmaku
from danmaku_inspector.types.models import CrawledDanmaku, DanmakuFingerprint
from danmaku_inspector.config.settings import NetworkConfig, DEFAULT_NETWORK_CONFIG

logger = logging.getLogger(__name__)

# 触发B站风控的业务码
RISK_CONTROL_CODES = frozenset({-352, -412, -509})

SEGMENT_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"


class BiliApiError(Exception):
    """B站 API 业务错误。

    Attributes:
        code (int): B站返回的业务错误码。
        message (str): B站返回的错误描述。
    """
    def __init__(self, code: int, message: str):
        """初始化业务错误。

        Args:
            code (int): B站返回的业务错误码。
            message (str): B站返回的错误描述。
        """
        self.code = code
        self.message = message
        super().__init__(f"Bili API Error [Code: {code}]: {message}")


class BiliNetworkError(Exception):
    """网络请求错误。

    Attributes:
        message (str): 错误描述。
    """
    def __init__(self, message: str):
        """初始化网络错误。

        Args:
            message (str): 错误描述。
        """
        self.message = message
        super().__init__(f"网络请求失败: {message}")


class RiskControlError(BiliNetworkError):
    """被B站风控。调用方应触发熔断并停止抓取，不重试。

    Attributes:
        code (int): B站返回的风控错误码。
    """
    def __init__(self, code: int, message: str):
        """初始化风控错误。

        Args:
            code (int): B站返回的风控错误码。
            message (str): B站返回的错误描述。
        """
        self.code = code
        BiliNetworkError.__init__(self, f"被B站风控 (code={code}): {message}")


class BiliApiClient:
    """B站 API 客户端。"""

    BASE_HEADER = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    }

    def __init__(self, sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> None:
        """初始化客户端。

        Args:
            sessdata (str): SESSDATA 值，为空表示匿名访问。
            config (NetworkConfig): 网络配置。
        """
        self._sessdata = sessdata
        self._config = config
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建请求会话。"""
        session = requests.Session()
        session.headers.update(self.BASE_HEADER)

        if self._sessdata:
            session.cookies.update({"SESSDATA": self._sessdata})

        return session

    @contextmanager
    def _network_guards(self, url: str) -> Generator[None, None, None]:
        """将 requests 异常统一转换为 BiliNetworkError。

        Args:
            url (str): 请求地址，仅用于日志。

        Yields:
            None: 上下文管理器。
        """
        try:
            yield
        except Timeout as e:
            logger.error(f"请求超时: {url}, Error: {e}")
            raise BiliNetworkError(f"请求超时: {e}") from e
        except ConnectionError as e:
            logger.error(f"连接失败: {url}, Error: {e}")
            raise BiliNetworkError(f"网络连接断开: {e}") from e
        except HTTPError as e:
            if e.response is None:
                logger.error(f"HTTP异常: {url}, 未收到服务器响应")
                raise BiliNetworkError("服务器未响应") from e
            status_code = e.response.status_code
            logger.error(f"HTTP错误: {url}, Status: {status_code}")
            if 500 <= status_code < 600:
                raise BiliNetworkError(f"B站服务器错误 ({status_code})") from e
            else:
                raise BiliNetworkError(f"请求被拒绝 ({status_code})") from e
        except RequestException as e:
            logger.error(f"请求异常: {url}, Error: {e}")
            raise BiliNetworkError(f"请求异常: {e}") from e

    def _request(self, method: str, url: str, **kwargs) -> Any:
        """发送 JSON API 请求并返回业务数据。

        Args:
            method (str): HTTP 方法。
            url (str): 请求地址。
            **kwargs: 传递给 requests 的参数，未指定 timeout 时取 config.timeout。

        Returns:
            Any: 响应 JSON 中的 data 字段。

        Raises:
            RiskControlError: B站返回风控错误码。
            BiliApiError: B站返回其他业务错误码。
            BiliNetworkError: 网络错误或响应非 JSON。
        """
        kwargs.setdefault("timeout", self._config.timeout)

        with self._network_guards(url):
            response = self._session.request(method, url, **kwargs)
            response.raise_for_status()
            data: dict = response.json()

            code = data.get("code", -1)
            if code == 0:
                return data.get("data", {})
            else:
                message = data.get("message", "未知错误")
                logger.warning(f"API请求失败: {url}, Code: {code}, Message: {message}")
                if code in RISK_CONTROL_CODES:
                    raise RiskControlError(code, message)
                raise BiliApiError(code=code, message=message)

    def get_video_info(self, bvid: str) -> dict:
        """获取视频元数据，含各分P的 cid 与时长。

        Args:
            bvid (str): 视频 BV 号。

        Returns:
            dict: 含 title、aid、pages 的元数据。
            pages 的键为分P号，值含 cid、title、duration，duration 单位为秒。

        Raises:
            BiliApiError: API 返回业务错误。
            BiliNetworkError: 网络错误。
        """
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
        logger.info(f"正在获取视频信息: {bvid}")
        data = self._request("GET", url, params=params)

        # 转换 pages 为字典格式，duration 用于推算分段总数
        pages = {}
        for i, page in enumerate(data.get("pages", []), start=1):
            pages[i] = {
                "cid": page["cid"],
                "title": page.get("part", ""),
                "duration": int(page.get("duration", 0) or 0),
            }

        return {
            "title": data.get("title", ""),
            "aid": data.get("aid", 0),
            "pages": pages,
        }

    def get_user_info(self) -> dict:
        """获取当前登录用户的信息。

        Returns:
            dict: 用户信息，含 mid、uname、level_info 等字段。

        Raises:
            BiliApiError: API 返回业务错误。
            BiliNetworkError: 网络错误。
        """
        url = "https://api.bilibili.com/x/web-interface/nav"
        return self._request("GET", url)

    def check_account(self) -> bool:
        """检测当前凭据是否有效。

        Returns:
            bool: 有效返回 True，失效返回 False。
        """
        try:
            self.get_user_info()
            return True
        except BiliApiError as e:
            if e.code in [-101, -102, -111]:
                return False
            raise
        except BiliNetworkError:
            raise

    def fetch_segment(self, cid: int, avid: int, segment_index: int) -> list[CrawledDanmaku]:
        """抓取单个分段，单次尝试。

        本方法不含重试与限流。分段内无弹幕时返回空列表，属于正常结果。

        Args:
            cid (int): 分P 的 cid。
            avid (int): 视频 avid。
            segment_index (int): 分段号，从 1 开始。

        Returns:
            list[CrawledDanmaku]: 该分段内的弹幕列表，可能为空。

        Raises:
            RiskControlError: 被B站风控。
            BiliApiError: B站返回业务错误。
            BiliNetworkError: 网络错误或响应解析失败。
        """
        url = SEGMENT_URL
        params = {
            "type": 1,
            "oid": cid,
            "pid": avid,
            "segment_index": segment_index,
        }

        with self._network_guards(url):
            resp = self._session.get(url, params=params, timeout=self._config.timeout)
            resp.raise_for_status()
            raw = resp.content

        data = self._decompress(raw)

        # 错误响应走 JSON 而不是 protobuf，先识别它
        error = self._parse_json_error(data, url)
        if error is not None:
            code, message = error
            if code in RISK_CONTROL_CODES:
                logger.error(f"被B站风控: code={code}, message={message}")
                raise RiskControlError(code, message)
            logger.error(f"B站返回错误: code={code}, message={message}")
            raise BiliApiError(code=code, message=message)

        try:
            seg = danmaku.DmSegMobileReply()
            seg.ParseFromString(data)
        except Exception as e:
            logger.error(f"分段解析失败: {url}, segment={segment_index}, Error: {e}")
            raise BiliNetworkError(f"分段解析失败: {e}") from e

        return [
            CrawledDanmaku(
                fingerprint=DanmakuFingerprint(
                    content=elem.content or "",
                    progress_ms=elem.progress,
                    mode=elem.mode,
                    fontsize=elem.fontsize,
                    color=elem.color,
                ),
                midhash=elem.midHash or "",
            )
            for elem in seg.elems
        ]

    @staticmethod
    def _decompress(raw: bytes) -> bytes:
        """解压 zlib 响应体，非 zlib 数据原样返回。

        Args:
            raw (bytes): 原始响应体。

        Returns:
            bytes: 解压后的数据。
        """
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return raw

    @staticmethod
    def _parse_json_error(data: bytes, url: str) -> tuple[int, str] | None:
        """将响应体解析为 JSON 错误。

        Args:
            data (bytes): 响应体。
            url (str): 请求地址，仅用于日志。

        Returns:
            tuple[int, str] | None: （业务错误码, 错误描述）；非 JSON 错误响应时为 None。
        """
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None

        code = payload.get("code", 0)
        message = payload.get("message", "")
        if code == 0:
            logger.warning(f"响应体是 JSON 但无错误码，按解析失败处理: {url}")
            return None
        return int(code), str(message)

    def close(self) -> None:
        """关闭会话。"""
        if self._session:
            self._session.close()

    def __enter__(self) -> "BiliApiClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """退出上下文时关闭会话。

        Args:
            exc_type (type | None): 异常类型。
            exc_value (BaseException | None): 异常实例。
            traceback (TracebackType | None): 调用堆栈。
        """
        self.close()
