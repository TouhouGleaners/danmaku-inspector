"""B站账号相关请求的便捷封装。"""
from danmaku_inspector.config.settings import NetworkConfig, DEFAULT_NETWORK_CONFIG

from .bili_api_client import BiliApiClient


def check_account(sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> bool:
    """检测凭据是否有效。

    Args:
        sessdata (str): SESSDATA 值。
        config (NetworkConfig): 网络配置。

    Returns:
        bool: 有效返回 True，失效返回 False。
    """
    with BiliApiClient(sessdata, config) as client:
        return client.check_account()


def get_user_info(sessdata: str, config: NetworkConfig = DEFAULT_NETWORK_CONFIG) -> dict:
    """获取当前登录用户的信息。

    Args:
        sessdata (str): SESSDATA 值。
        config (NetworkConfig): 网络配置。

    Returns:
        dict: 用户信息，含 mid、uname、level_info 等字段。
    """
    with BiliApiClient(sessdata, config) as client:
        return client.get_user_info()
