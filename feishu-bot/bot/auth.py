"""
飞书 tenant_access_token 生命周期管理器。
"""

import time
from typing import Optional

import httpx
from loguru import logger


class TokenManager:
    """管理飞书 tenant_access_token，支持自动刷新。"""

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    # 在过期前 5 分钟（300 秒）刷新 token
    REFRESH_BUFFER_SECONDS = 300

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: Optional[str] = None
        self._expires_at: float = 0
        self._client = httpx.AsyncClient(timeout=30.0)

    async def get_token(self) -> str:
        """
        返回有效的 tenant_access_token。
        如果 token 已过期或即将过期，则自动刷新。
        """
        if self._token and time.time() < (self._expires_at - self.REFRESH_BUFFER_SECONDS):
            return self._token

        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        """
        从飞书 API 获取新的 tenant_access_token。

        POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
        请求体：{ "app_id": "...", "app_secret": "..." }
        """
        payload = {
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }

        try:
            response = await self._client.post(self.TOKEN_URL, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                msg = data.get("msg", "Unknown error")
                logger.error(f"Failed to refresh tenant_access_token: {msg}")
                raise RuntimeError(f"Token refresh failed: {msg}")

            self._token = data["tenant_access_token"]
            expire_in = data.get("expire", 7200)  # 默认 2 小时
            self._expires_at = time.time() + expire_in

            logger.info(
                f"Successfully refreshed tenant_access_token, "
                f"expires in {expire_in} seconds"
            )
            return self._token

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"HTTP error while refreshing token: "
                f"{exc.response.status_code} - {exc.response.text}"
            )
            raise
        except httpx.RequestError as exc:
            logger.error(f"Request error while refreshing token: {exc}")
            raise

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self._client.aclose()
        logger.info("TokenManager HTTP client closed")
