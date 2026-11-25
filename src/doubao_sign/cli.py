"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import DoubaoClient, DoubaoSession


def _load_session(path: Path) -> DoubaoSession:
    return DoubaoSession(**json.loads(path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a browser-free Doubao chat request")
    parser.add_argument("prompt")
    parser.add_argument("--session", type=Path, default=Path(".local/session.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    client = DoubaoClient(_load_session(args.session))
    body = client.serialize_body(client.build_body(args.prompt))
    if args.dry_run:
        print(json.dumps({"url": client.build_signed_url(body), "body": json.loads(body)}, ensure_ascii=False, indent=2))
        return 0
    for event in client.stream(args.prompt):
        print(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

