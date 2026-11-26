"""Interactive console for a persistent Doubao client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .client import DoubaoProtocolError
from .modes import (
    DEFAULT_MODE,
    FunctionMode,
    ModeSelection,
    available_combinations,
    available_image_models,
)


class StreamingClient(Protocol):
    def stream_text(
        self,
        prompt: str,
        *,
        mode: ModeSelection | None = None,
        artifact_root: Path | None = None,
    ): ...


def _mode_menu() -> str:
    return "\n".join(
        f"{index}. {selection.label}"
        for index, selection in enumerate(available_combinations(), start=1)
    )


def _image_model_menu() -> str:
    return "\n".join(
        f"{index}. {model.value}"
        for index, model in enumerate(available_image_models(), start=1)
    )


def select_image_model(
    selection: ModeSelection,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None],
) -> ModeSelection | None:
    models = available_image_models()
    output_fn(f"可用图像模型：\n{_image_model_menu()}\n")
    while True:
        try:
            raw = input_fn(f"请选择图像模型 [1-{len(models)}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        try:
            index = int(raw)
        except ValueError:
            index = 0
        if 1 <= index <= len(models):
            return replace(selection, image_model=models[index - 1])
        output_fn(f"请输入 1-{len(models)}。\n")


def select_mode(
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None],
) -> ModeSelection | None:
    """Prompt until the user selects one observed, supported combination."""
    combinations = available_combinations()
    output_fn(f"可用模式：\n{_mode_menu()}\n")
    while True:
        try:
            raw = input_fn(f"请选择模式 [1-{len(combinations)}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        try:
            index = int(raw)
        except ValueError:
            index = 0
        if 1 <= index <= len(combinations):
            selection = combinations[index - 1]
            if selection.function is FunctionMode.IMAGE:
                return select_image_model(
                    selection, input_fn=input_fn, output_fn=output_fn
                )
            return selection
        output_fn(f"请输入 1-{len(combinations)}。\n")


def run_console(
    client: StreamingClient,
    *,
    initial_mode: ModeSelection = DEFAULT_MODE,
    artifact_root: Path | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None],
) -> None:
    """Read questions until the user exits, printing response chunks as received."""
    mode = initial_mode
    while True:
        try:
            prompt = input_fn(f"你[{mode.label}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if prompt.lower() in {"exit", "quit"} or prompt == "退出":
            return
        if not prompt:
            continue
        if prompt == "/mode":
            selected = select_mode(input_fn=input_fn, output_fn=output_fn)
            if selected is None:
                return
            mode = selected
            output_fn(f"已切换：{mode.label}\n")
            continue
        if prompt == "/modes":
            output_fn(f"可用模式：\n{_mode_menu()}\n")
            continue
        if prompt == "/help":
            output_fn("命令：/mode 切换模式；/modes 查看模式；/help 查看帮助；退出 结束。\n")
            continue
        output_fn("豆包> ")
        try:
            for text in client.stream_text(
                prompt, mode=mode, artifact_root=artifact_root
            ):
                output_fn(text)
        except DoubaoProtocolError as exc:
            output_fn(f"错误: {exc}")
        output_fn("\n")

