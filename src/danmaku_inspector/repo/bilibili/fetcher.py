"""B站 Protobuf 弹幕抓取器。

通过 B站 API 抓取线上全量弹幕，解析为 Counter[DanmakuFingerprint]。
"""
import json
import logging
import time
import zlib
from collections import Counter

import requests

from ..protobuf import dm_pb2 as danmaku
from danmaku_inspector.types.models import DanmakuFingerprint
from danmaku_inspector.config.settings import NetworkConfig, DEFAULT_NETWORK_CONFIG

logger = logging.getLogger(__name__)


def get_video_info(bvid: str, cookie: str) -> dict:
    """获取视频元数据，包括所有分P的 cid。

    Args:
        bvid: 视频 BV 号。
        cookie: Cookie 字符串 (SESSDATA=xxx)。

    Returns:
        视频元数据，包含 title、aid、pages。

    Raises:
        requests.HTTPError: 请求失败。
    """
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": cookie}

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()["data"]

    pages = {}
    for i, page in enumerate(data["pages"], start=1):
        pages[i] = {"cid": page["cid"], "title": page["part"]}

    return {
        "title": data["title"],
        "aid": data["aid"],
        "pages": pages,
    }


def fetch_part(
    cid: int,
    avid: int,
    cookie: str,
    config: NetworkConfig = DEFAULT_NETWORK_CONFIG,
) -> tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]:
    """抓取单个分P的全量弹幕。

    Args:
        cid: 分P 的 cid。
        avid: 视频 avid。
        cookie: Cookie 字符串。
        config: 网络配置。

    Returns:
        (online_counter, sender_map)
        - online_counter: 该分P的全量弹幕 Counter。
        - sender_map: {midhash: Counter} 发送者映射。

    Raises:
        RuntimeError: 被B站风控时抛出。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": cookie,
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
        for retry in range(config.max_retries):
            try:
                resp = requests.get(
                    "https://api.bilibili.com/x/v2/dm/web/seg.so",
                    params=params,
                    headers=headers,
                    timeout=config.timeout,
                )
                resp.raise_for_status()
                break
            except Exception as e:
                if retry == config.max_retries - 1:
                    logger.warning(f"cid={cid} 第 {segment} 段请求失败，终止")
                    return online_counter, sender_map
                logger.debug(f"请求失败，第 {retry + 1} 次重试: {e}")
                time.sleep(config.request_interval)

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
            # 风控错误
            if error_code in [-352, -412, -509]:
                raise RuntimeError(f"被B站风控了 (code={error_code})，请稍后再试")
            break
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        # 解析 Protobuf
        try:
            danmaku_seg = danmaku.DmSegMobileReply()
            danmaku_seg.ParseFromString(data)
        except Exception as e:
            logger.error(f"解析失败: {e}")
            logger.error(f"数据长度: {len(data)}")
            break

        # 没有弹幕了，结束
        if not danmaku_seg.elems:
            break

        # 处理每条弹幕
        for elem in danmaku_seg.elems:
            content = elem.content or ""
            fp = DanmakuFingerprint(
                content=content,
                progress_ms=elem.progress,  # 线上已经是毫秒
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
        time.sleep(config.request_interval)

    logger.info(f"cid={cid} 抓取完成，共 {sum(online_counter.values())} 条")
    return online_counter, sender_map
