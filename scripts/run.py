"""Run a persistent Doubao SSE chat in this console."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doubao_sign.client import DoubaoClient, DoubaoSession
from doubao_sign.console import run_console, select_mode


LOGIN_ENABLED = False  # True: 每次扫码；False: 优先读取 .local/session.json


def resolve_session_file(root: Path = ROOT, *, login_enabled: bool = LOGIN_ENABLED) -> Path:
    session_file = root / ".local" / "session.json"
    if login_enabled or not session_file.is_file():
        from doubao_sign.login import scan_login

        return scan_login(session_file)
    return session_file


def main() -> int:
    try:
        session_file = resolve_session_file()
        session = DoubaoSession(
            **json.loads(session_file.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"登录或配置失败：{exc}")
        return 2
    client = DoubaoClient(session)
    print("豆包 SSE 控制台已启动；输入 /help 查看命令。")
    mode = select_mode(
        output_fn=lambda text: print(text, end="", flush=True),
    )
    if mode is None:
        print()
        return 0
    run_console(
        client,
        initial_mode=mode,
        artifact_root=ROOT / "outputs",
        output_fn=lambda text: print(text, end="", flush=True),
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
