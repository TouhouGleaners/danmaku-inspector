"""配置管理器。

负责配置的持久化和加载。
"""
import json
import logging

from pydantic import ValidationError, BaseModel

from danmaku_inspector.config.app_meta import AppInfo
from danmaku_inspector.config.settings import InspectionConfig, NetworkConfig

logger = logging.getLogger("App.System.Config")

CONFIG_PATH = AppInfo.Paths.CONFIG


class AppConfig(BaseModel):
    """应用配置。"""
    inspection: InspectionConfig = InspectionConfig()
    network: NetworkConfig = NetworkConfig()


class ConfigManager:
    """配置管理器。"""

    def save(self, config: AppConfig) -> None:
        """保存配置到文件。

        Args:
            config: 应用配置。
        """
        try:
            config_data = config.model_dump()
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            logger.info(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def load(self) -> AppConfig:
        """从文件加载配置。

        Returns:
            应用配置，文件不存在或解析失败返回默认配置。
        """
        if not CONFIG_PATH.exists():
            logger.info("未找到配置文件，使用默认设置。")
            return AppConfig()

        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式损坏，将使用默认设置[{CONFIG_PATH}]: {e}")
            return AppConfig()
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            return AppConfig()

        try:
            config = AppConfig.model_validate(data)
            logger.info(f"配置文件加载与校验流程结束[{CONFIG_PATH}]。")
            return config
        except ValidationError as e:
            logger.warning(f"配置存在非法值，已回退为安全默认值。详情:\n{e}")
            return AppConfig()
