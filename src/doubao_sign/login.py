"""Open Doubao for QR login and save a private API session."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import parse_qs, urlsplit

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from .client import DoubaoSession


CHAT_URL = "https://www.doubao.com/chat/"
_REQUIRED_QUERY = ("device_id", "tea_uuid", "web_id", "web_tab_id", "msToken", "fp")


class LoginError(RuntimeError):
    """The browser login could not produce a usable session."""


def _browser_cookies(driver: webdriver.Chrome) -> list[dict]:
    return driver.execute_cdp_cmd("Network.getAllCookies", {}).get("cookies", [])


def _logged_in(cookies: list[dict]) -> bool:
    names = {
        item.get("name")
        for item in cookies
        if str(item.get("domain", "")).lstrip(".").endswith("doubao.com")
    }
    return "sid_guard" in names and bool({"sessionid", "sessionid_ss"} & names)


def _cookie_header(cookies: list[dict]) -> str:
    return "; ".join(
        f"{item['name']}={item['value']}"
        for item in cookies
        if str(item.get("domain", "")).lstrip(".").endswith(
            ("doubao.com", "bytedance.com")
        )
        and item.get("name")
        and item.get("value")
    )


def _completion_request(logs: list[dict]) -> tuple[str, str]:
    """Find the latest completion URL and its exact Cookie request header."""
    requests: list[tuple[str, str]] = []
    headers_by_id: dict[str, str] = {}
    for item in logs:
        try:
            event = json.loads(item["message"])["message"]
            method = event["method"]
            params = event["params"]
        except (KeyError, TypeError, ValueError):
            continue
        request_id = str(params.get("requestId", ""))
        if method == "Network.requestWillBeSent":
            url = params.get("request", {}).get("url", "")
            parsed = urlsplit(url)
            if parsed.hostname == "www.doubao.com" and parsed.path == "/chat/completion":
                requests.append((request_id, url))
        elif method == "Network.requestWillBeSentExtraInfo":
            headers = params.get("headers", {})
            cookie = next(
                (value for key, value in headers.items() if key.lower() == "cookie"), ""
            )
            if cookie:
                headers_by_id[request_id] = cookie
    if not requests:
        return "", ""
    request_id, url = requests[-1]
    return url, headers_by_id.get(request_id, "")


def _room_id(url: str) -> str:
    match = re.fullmatch(r"/chat/([0-9]+)", urlsplit(url).path.rstrip("/"))
    return match.group(1) if match else ""


def build_session(completion_url: str, cookie: str, room_id: str) -> DoubaoSession:
    parsed = urlsplit(completion_url)
    if parsed.hostname != "www.doubao.com" or parsed.path != "/chat/completion":
        raise LoginError("未捕获到豆包聊天请求")
    query = parse_qs(parsed.query)
    missing = [key for key in _REQUIRED_QUERY if not query.get(key)]
    if missing:
        raise LoginError(f"聊天请求缺少参数：{', '.join(missing)}")
    if not cookie or "sessionid=" not in cookie:
        raise LoginError("登录 Cookie 不完整")
    if not room_id.isdigit():
        raise LoginError("未取得新对话 ID")
    return DoubaoSession(
        cookie=cookie,
        device_id=query["device_id"][0],
        tea_uuid=query["tea_uuid"][0],
        web_id=query["web_id"][0],
        web_tab_id=query["web_tab_id"][0],
        ms_token=query["msToken"][0],
        fp=query["fp"][0],
        room_id=room_id,
        region=query.get("region", ["HK"])[0],
    )


def save_session(session: DoubaoSession, path: Path) -> None:
    """Replace the credential file only after every field is available."""
    from dataclasses import asdict

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def scan_login(path: Path, *, login_timeout: float = 600) -> Path:
    """Let the user scan in a visible Chrome window, then capture one chat request."""
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    options = Options()
    options.page_load_strategy = "eager"
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver_path = shutil.which("chromedriver")
    service = Service(executable_path=driver_path) if driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.set_page_load_timeout(60)
        driver.execute_cdp_cmd("Network.enable", {})
        driver.get(CHAT_URL)
        if not _logged_in(_browser_cookies(driver)):
            login_button = WebDriverWait(driver, 30).until(
                lambda browser: browser.find_element(
                    By.CSS_SELECTOR, '[data-testid="to_login_button"]'
                )
            )
            login_button.click()
            print(
                "请在浏览器窗口勾选协议、选择抖音一键登录并扫码；"
                "完成后将自动提取并保存会话。",
                flush=True,
            )
            deadline = time.monotonic() + login_timeout
            while time.monotonic() < deadline:
                if _logged_in(_browser_cookies(driver)):
                    break
                time.sleep(1)
            else:
                raise LoginError("扫码登录超时或未完成")

        driver.switch_to.window(driver.window_handles[0])
        driver.get(CHAT_URL)
        editor = WebDriverWait(driver, 45).until(
            lambda browser: browser.find_element(By.CSS_SELECTOR, '[contenteditable="true"]')
        )
        driver.get_log("performance")
        editor.send_keys("你好")
        editor.send_keys(Keys.ENTER)
        print("已登录，正在初始化对话并获取请求参数……", flush=True)

        deadline = time.monotonic() + 120
        logs: list[dict] = []
        while time.monotonic() < deadline:
            logs.extend(driver.get_log("performance"))
            url, request_cookie = _completion_request(logs)
            room = _room_id(driver.current_url)
            if url and room:
                cookie = request_cookie or _cookie_header(_browser_cookies(driver))
                session = build_session(url, cookie, room)
                save_session(session, path)
                print(f"登录会话已保存：{path.resolve()}", flush=True)
                return path
            time.sleep(1)
        raise LoginError("登录成功，但未捕获到完整聊天请求或新对话 ID")
    finally:
        driver.quit()
