"""FanboxClient：用 curl_cffi 带 chrome 指纹绕过 fanbox 的反爬。

移植自 src/ts/API.ts:28-57 的 request 方法 + 浏览器自带的 cookie/UA/referer。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from curl_cffi import requests as curl_requests

from api.exceptions import (
    FanboxAPIError,
    FanboxAuthError,
    FanboxForbiddenError,
    FanboxRateLimitError,
)
from crawler.interval import CrawlInterval

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20


class FanboxClient:
    """对 Fanbox API 做最薄的封装。所有端点 wrapper 见 api/endpoints.py。"""

    def __init__(
        self,
        session_cookie: str,
        user_agent: str,
        interval: CrawlInterval,
        proxy: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if not session_cookie:
            raise FanboxAuthError("session_cookie 为空")

        self.interval = interval
        self.timeout = timeout

        self.session = curl_requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                "Origin": "https://www.fanbox.cc",
                "Referer": "https://www.fanbox.cc/",
            }
        )
        # FANBOXSESSID 是唯一必要的 cookie
        self.session.cookies.update({"FANBOXSESSID": session_cookie})

    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """发送 GET 请求并解析 JSON。

        - 自动等待 interval；
        - 429 → bump("long") + FanboxRateLimitError；
        - 401/403 → FanboxAuthError；
        - 5xx / 解析失败 → FanboxAPIError；
        - 成功 → bump("short") + 返回 json。
        """
        self.interval.wait()
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
                impersonate="chrome120",
            )
        except Exception as exc:  # 网络/超时
            self.interval.bump("long")
            raise FanboxAPIError(f"请求失败: {url} - {exc}") from exc

        status = resp.status_code

        if status == 429:
            self.interval.bump("long")
            raise FanboxRateLimitError(f"429 Too Many Requests: {url}")

        if status == 401:
            raise FanboxAuthError(
                f"401 认证失败：FANBOX_SESSION cookie 已失效。URL: {url}"
            )

        if status == 403:
            # fanbox 对单条资源的 403 通常是"付费等级不足/限定内容"，
            # 不代表 cookie 失效。调用方应跳过这条继续。
            raise FanboxForbiddenError(
                f"403 无权访问该资源（可能是付费等级不足或限定内容）: {url}"
            )

        if status >= 500:
            self.interval.bump("long")
            raise FanboxAPIError(f"{status} 服务端错误: {url}")

        if status >= 400:
            raise FanboxAPIError(f"{status} 客户端错误: {url}")

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise FanboxAPIError(f"响应不是合法 JSON: {url}") from exc

        # fanbox 也可能在 200 里返回 {"error": "..."}
        if isinstance(data, dict) and "error" in data and "body" not in data:
            raise FanboxAPIError(f"业务错误 {url}: {data.get('error')}")

        self.interval.bump("short")
        return data
