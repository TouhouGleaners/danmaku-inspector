"""B站弹幕抓取器。

封装 BiliApiClient，提供简化的弹幕抓取接口。
"""
from collections import Counter

from danmaku_inspector.types.models import DanmakuFingerprint
from danmaku_inspector.config.settings import NetworkConfig, DEFAULT_NETWORK_CONFIG

from .bili_api_client import BiliApiClient


def get_video_info(bvid: str, sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> dict:
    """获取视频元数据，包括所有分P的 cid。

    Args:
        bvid: 视频 BV 号。
        sessdata: SESSDATA 值。
        config: 网络配置。

    Returns:
        视频元数据，包含 title、aid、pages。
    """
    with BiliApiClient(sessdata, config) as client:
        return client.get_video_info(bvid)


def fetch_part(
    cid: int,
    avid: int,
    sessdata: str,
    config: NetworkConfig = DEFAULT_NETWORK_CONFIG,
) -> tuple[Counter[DanmakuFingerprint], dict[str, Counter[DanmakuFingerprint]]]:
    """抓取单个分P的全量弹幕。

    Args:
        cid: 分P 的 cid。
        avid: 视频 avid。
        sessdata: SESSDATA 值。
        config: 网络配置。

    Returns:
        (online_counter, sender_map)
    """
    with BiliApiClient(sessdata, config) as client:
        return client.fetch_part_danmaku(cid, avid)


def check_account(sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> bool:
    """检测账号是否有效。

    Args:
        sessdata: SESSDATA 值。
        config: 网络配置。

    Returns:
        True 表示有效。
    """
    with BiliApiClient(sessdata, config) as client:
        return client.check_account()


def get_user_info(sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> dict:
    """获取当前登录用户的信息。

    Args:
        sessdata: SESSDATA 值。
        config: 网络配置。

    Returns:
        用户信息。
    """
    with BiliApiClient(sessdata, config) as client:
        return client.get_user_info()
