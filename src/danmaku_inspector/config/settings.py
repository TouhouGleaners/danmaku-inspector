"""配置文件。

集中管理所有可配置的阈值和参数。
"""
from dataclasses import dataclass


@dataclass
class InspectionConfig:
    """校验阈值配置。

    Attributes:
        extra_threshold: 单个账号在 Extra 池中的贡献条数阈值，低于此值认为是路人散兵。
        match_threshold: 跨P匹配率阈值，高于此值认为是错发。
        extra_rate_threshold: 错发率阈值，高于此值显示错发状态。
        unsent_rate_threshold: 漏发率阈值，高于此值显示漏发状态。
    """
    extra_threshold: int = 15
    match_threshold: float = 0.7
    extra_rate_threshold: float = 0.05
    unsent_rate_threshold: float = 0.1


@dataclass
class NetworkConfig:
    """网络请求配置。

    Attributes:
        request_interval: B站 API 请求间隔（秒）。
        max_retries: 请求失败重试次数。
        timeout: 请求超时时间（秒）。
    """
    request_interval: float = 0.5
    max_retries: int = 3
    timeout: int = 15


# 默认配置实例
DEFAULT_INSPECTION_CONFIG = InspectionConfig()
DEFAULT_NETWORK_CONFIG = NetworkConfig()
