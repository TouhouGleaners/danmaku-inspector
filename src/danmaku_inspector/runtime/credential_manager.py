"""凭据管理器。

负责 Cookie 的加密存储和加载。
使用 keyring 存储加密密钥，使用 Fernet 加密凭据。
"""
import json
import logging
import os
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel

from danmaku_inspector.config.app_meta import AppInfo

logger = logging.getLogger("App.System.Credential")

KEYRING_SERVICE_NAME = f"{AppInfo.NAME_EN}-CredentialsKey"
KEYRING_USERNAME = "default_user"
ACCOUNTS_PATH = AppInfo.Paths.ACCOUNTS


class Credential(BaseModel):
    """已保存的凭据。"""
    name: str = ""
    cookie: str = ""


class CredentialManager:
    """凭据管理器。"""

    def _get_encryption_key(self) -> tuple[bytes, bool]:
        """从系统密钥环获取加密密钥。

        Returns:
            (key, persisted): 密钥字节，以及密钥是否已持久化到密钥环。
        """
        try:
            key_str = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME)
        except Exception as e:
            logger.warning(f"密钥环读取失败: {e}，将生成新密钥。")
            key_str = None

        if key_str:
            logger.debug("已从系统密钥环获取加密密钥。")
            return key_str.encode('utf-8'), True

        new_key = Fernet.generate_key()
        try:
            keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_USERNAME, new_key.decode('utf-8'))
            logger.info("已生成新的加密密钥并存储在系统密钥环中。")
            return new_key, True
        except Exception as e:
            logger.warning(f"密钥环写入失败: {e}，密钥仅在本次会话有效，跳过凭据持久化。")
            return new_key, False

    def load_credentials(self) -> list[Credential]:
        """从加密文件加载凭据列表。

        Returns:
            凭据列表，文件不存在或解密失败返回空列表。
        """
        if not ACCOUNTS_PATH.exists():
            return []

        try:
            key, _ = self._get_encryption_key()
            fernet = Fernet(key)

            encrypted_data = ACCOUNTS_PATH.read_bytes()
            decrypted_data = fernet.decrypt(encrypted_data)

            raw_list = json.loads(decrypted_data.decode('utf-8'))

            if not isinstance(raw_list, list):
                logger.warning("凭据文件格式异常：顶层不是列表，已备份。")
                self._backup_corrupt_file(ACCOUNTS_PATH)
                return []

            credentials = []
            for i, item in enumerate(raw_list):
                try:
                    credentials.append(Credential.model_validate(item))
                except Exception as e:
                    logger.warning(f"跳过格式异常的凭据条目 (index={i}): {e}")

            logger.info(f"已加载 {len(credentials)} 个保存的凭据。")
            return credentials

        except InvalidToken:
            logger.warning("凭据文件解密失败（密钥不匹配），文件已保留。")
            return []

        except json.JSONDecodeError as e:
            logger.warning(f"凭据文件 JSON 解析失败（文件损坏）: {e}")
            self._backup_corrupt_file(ACCOUNTS_PATH)
            return []

        except Exception as e:
            logger.critical(f"加载凭据数据时发生意外错误: {e}", exc_info=True)
            raise

    def save_credentials(self, credentials: list[Credential]) -> None:
        """将凭据列表加密后写入文件。

        Args:
            credentials: 凭据列表。
        """
        if not credentials:
            logger.info("凭据列表为空，删除凭据文件。")
            if ACCOUNTS_PATH.exists():
                try:
                    os.remove(ACCOUNTS_PATH)
                except OSError as e:
                    logger.error(f"删除凭据文件失败: {e}", exc_info=True)
            return

        try:
            key, persisted = self._get_encryption_key()
            if not persisted:
                logger.warning("密钥未持久化，跳过凭据写盘以避免产生无法解密的文件。")
                return

            f = Fernet(key)

            raw_list = [cred.model_dump() for cred in credentials]
            json_bytes = json.dumps(raw_list, ensure_ascii=False).encode('utf-8')
            encrypted_bytes = f.encrypt(json_bytes)

            ACCOUNTS_PATH.write_bytes(encrypted_bytes)
            logger.info(f"已保存 {len(credentials)} 个凭据到 {ACCOUNTS_PATH}")
        except Exception as e:
            logger.error(f"保存凭据数据失败: {e}", exc_info=True)

    @staticmethod
    def _backup_corrupt_file(path: Path) -> None:
        """将损坏的文件备份为 .corrupt 后缀。"""
        try:
            backup = path.with_suffix(".json.corrupt")
            path.rename(backup)
            logger.info(f"已将损坏的文件备份为: {backup}")
        except OSError as e:
            logger.error(f"无法备份损坏的文件: {e}")
