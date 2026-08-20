"""B站 API 客户端。

封装所有与 B站 API 的交互，包括：
- 视频信息获取
- 用户信息获取
- 账号检测
- 弹幕抓取
"""
import json
import logging
import time
import zlib
from collections import Counter
from contextlib import contextmanager
from typing import Any, Generator

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from ..protobuf import dm_pb2 as danmaku
from danmaku_inspector.types.models import DanmakuFingerprint
from danmaku_inspector.config.settings import NetworkConfig, DEFAULT_NETWORK_CONFIG

logger = logging.getLogger(__name__)


class BiliApiError(Exception):
    """B站 API 业务错误。"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Bili API Error [Code: {code}]: {message}")


class BiliNetworkError(Exception):
    """网络请求错误。"""
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"网络请求失败: {message}")


class BiliApiClient:
    """B站 API 客户端。"""

    BASE_HEADER = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    }

    def __init__(self, sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> None:
        """初始化客户端。

        Args:
            sessdata: SESSDATA 值。
            config: 网络配置。
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
        """统一的网络异常捕获。"""
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
        """通用 JSON API 请求。"""
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
                raise BiliApiError(code=code, message=message)

    def get_video_info(self, bvid: str) -> dict:
        """获取视频元数据，包括所有分P的 cid。

        Args:
            bvid: 视频 BV 号。

        Returns:
            视频元数据，包含 title、aid、pages。

        Raises:
            BiliApiError: API 返回错误。
            BiliNetworkError: 网络错误。
        """
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
        logger.info(f"正在获取视频信息: {bvid}")
        return self._request("GET", url, params=params)

    def get_user_info(self) -> dict:
        """获取当前登录用户的信息。

        Returns:
            用户信息，包含 uid、nickname、level 等。

        Raises:
            BiliApiError: API 返回错误。
            BiliNetworkError: 网络错误。
        """
        url = "https://api.bilibili.com/x/web-interface/nav"
        return self._request("GET", url)

    def check_account(self) -> bool:
        """检测账号是否有效。

        Returns:
            True 表示有效，False 表示失效。
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

    def fetch_part_danmaku(
        self,
        cid: int,
        avid: int,
    ) -> tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]:
        """抓取单个分P的全量弹幕。

        Args:
            cid: 分P 的 cid。
            avid: 视频 avid。

        Returns:
            (online_counter, sender_map)
            - online_counter: 该分P的全量弹幕 Counter。
            - sender_map: {midhash: Counter} 发送者映射。

        Raises:
            BiliNetworkError: 被B站风控时抛出。
        """
        headers = {
            **self.BASE_HEADER,
            "Cookie": f"SESSDATA={self._sessdata}",
        }

        online_counter: Counter[DanmakuFingerprint] = Counter()
        sender_map: dict[str, Counter[DanmakuFingerprint]] = {}

        segment = 1
        while True:
            params = {
                "type": 1,
                "oid": cid,
                "pid": avid,
                "segment_index": segment,
            }

            # 请求重试
            for retry in range(self._config.max_retries):
                try:
                    resp = self._session.get(
                        "https://api.bilibili.com/x/v2/dm/web/seg.so",
                        params=params,
                        headers=headers,
                        timeout=self._config.timeout,
                    )
                    resp.raise_for_status()
                    break
                except Exception as e:
                    if retry == self._config.max_retries - 1:
                        logger.warning(f"cid={cid} 第 {segment} 段请求失败，终止")
                        return online_counter, sender_map
                    logger.debug(f"请求失败，第 {retry + 1} 次重试: {e}")
                    time.sleep(self._config.request_interval)

            # 处理压缩数据
            try:
                data = zlib.decompress(resp.content)
            except zlib.error:
                data = resp.content

            # 检查是否是 JSON 错误
            try:
                error_data = json.loads(data)
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                logger.error(f"B站返回错误: code={error_code}, message={error_msg}")
                if error_code in [-352, -412, -509]:
                    raise BiliNetworkError(f"被B站风控了 (code={error_code})，请稍后再试")
                break
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            # 解析 Protobuf
            try:
                danmaku_seg = danmaku.DmSegMobileReply()
                danmaku_seg.ParseFromString(data)
            except Exception as e:
                logger.error(f"解析失败: {e}")
                break

            # 没有弹幕了，结束
            if not danmaku_seg.elems:
                break

            # 处理每条弹幕
            for elem in danmaku_seg.elems:
                content = elem.content or ""
                fp = DanmakuFingerprint(
                    content=content,
                    progress_ms=elem.progress,
                    mode=elem.mode,
                    fontsize=elem.fontsize,
                    color=elem.color,
                )
                online_counter[fp] += 1

                # 构建 Sender Map
                midhash = elem.midHash
                if midhash not in sender_map:
                    sender_map[midhash] = Counter()
                sender_map[midhash][fp] += 1

            segment += 1
            time.sleep(self._config.request_interval)

        logger.info(f"cid={cid} 抓取完成，共 {sum(online_counter.values())} 条")
        return online_counter, sender_map

    def close(self) -> None:
        """关闭会话。"""
        if self._session:
            self._session.close()

    def __enter__(self) -> "BiliApiClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
