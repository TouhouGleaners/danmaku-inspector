"""配置文件。

集中管理所有可配置的阈值和参数。
"""
from dataclasses import dataclass


@dataclass
class InspectionConfig:
    """校验阈值配置。

    Attributes:
        extra_threshold (int): 单个账号在 Extra 池中的贡献条数阈值，低于此值不归因。
        match_threshold (float): 跨P匹配率阈值，高于此值判为错发。
        extra_rate_threshold (float): 错发率阈值，高于此值显示错发状态。
        unsent_rate_threshold (float): 漏发率阈值，高于此值显示漏发状态。
    """
    extra_threshold: int = 15
    match_threshold: float = 0.7
    extra_rate_threshold: float = 0.05
    unsent_rate_threshold: float = 0.1


@dataclass
class NetworkConfig:
    """网络与抓取调度配置。

    Attributes:
        timeout (int): 单次请求超时（秒）。
        max_retries (int): 单段请求的最大尝试次数，含首次。
        retry_backoff (float): 重试退避基数（秒），按 2^n 增长。
        rate_per_second (float): 全局请求速率上限（个/秒）。
        rate_burst (int): 令牌桶突发容量。
        part_concurrency (int): 同时抓取的分P数量上限。
        segment_seconds (int): 单段覆盖的时间轴长度（秒），B站为 360。
    """
    timeout: int = 15
    max_retries: int = 3
    retry_backoff: float = 1.5
    rate_per_second: float = 2.0
    rate_burst: int = 3
    part_concurrency: int = 3
    segment_seconds: int = 360


# 默认配置实例
DEFAULT_INSPECTION_CONFIG = InspectionConfig()
DEFAULT_NETWORK_CONFIG = NetworkConfig()
