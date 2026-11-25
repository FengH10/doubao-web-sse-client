"""msToken protocol client.

``msToken`` is issued by ByteDance's token service.  It is not an offline
hash.  This module implements the browser-free wire protocol and accepts the
already serialized device-fingerprint string as input.
"""

from __future__ import annotations

import json
import time
from email.message import Message
from http.cookies import SimpleCookie
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


def build_token_payload(str_data: str, *, now_ms: int | None = None) -> dict[str, int | str]:
    if not str_data:
        raise ValueError("str_data must contain the serialized device fingerprint")
    return {
        "magic": 0x20200422,
        "version": 1,
        "dataType": 8,
        "strData": str_data,
        "tspFromClient": now_ms if now_ms is not None else int(time.time() * 1000),
        "ulr": 0,
    }


def extract_ms_token(set_cookie_headers: list[str]) -> str:
    for value in set_cookie_headers:
        cookie = SimpleCookie()
        cookie.load(value)
        if "msToken" in cookie:
            return cookie["msToken"].value
    raise RuntimeError("token service response did not set msToken")


class MsTokenClient:
    def __init__(self, *, app_id: str = "6383", user_agent: str = DEFAULT_USER_AGENT):
        self.app_id = app_id
        self.user_agent = user_agent

    def issue(self, str_data: str, *, timeout: float = 15.0) -> str:
        body = json.dumps(build_token_payload(str_data), separators=(",", ":")).encode()
        request = Request(
            f"https://mssdk.bytedance.com/web/r/token?ms_appid={self.app_id}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Referer": "https://www.doubao.com/",
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=timeout) as response:
            headers: Message = response.headers
            return extract_ms_token(headers.get_all("Set-Cookie", []))

