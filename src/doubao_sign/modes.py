"""Typed console mode selections and request-body overlays."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum


class FunctionMode(str, Enum):
    CHAT = "普通对话"
    IMAGE = "图像生成"
    PPT = "PPT 生成"
    WRITING = "帮我写作"


class AnswerMode(str, Enum):
    FAST = "快速"
    DEEP = "深度思考"
    SEARCH = "联网搜索（自动触发）"


@dataclass(frozen=True)
class ModeSelection:
    function: FunctionMode
    answer: AnswerMode

    @property
    def label(self) -> str:
        return f"{self.function.value}/{self.answer.value}"


class UnsupportedModeCombination(ValueError):
    """The web client does not expose this function/answer combination."""


_AVAILABLE = (
    ModeSelection(FunctionMode.CHAT, AnswerMode.FAST),
    ModeSelection(FunctionMode.CHAT, AnswerMode.DEEP),
    ModeSelection(FunctionMode.CHAT, AnswerMode.SEARCH),
    ModeSelection(FunctionMode.IMAGE, AnswerMode.FAST),
    ModeSelection(FunctionMode.PPT, AnswerMode.FAST),
    ModeSelection(FunctionMode.WRITING, AnswerMode.FAST),
)
DEFAULT_MODE = _AVAILABLE[0]


def available_combinations() -> tuple[ModeSelection, ...]:
    return _AVAILABLE


def _validate(selection: ModeSelection) -> None:
    if selection not in _AVAILABLE:
        raise UnsupportedModeCombination(f"不支持的模式组合：{selection.label}")


def apply_mode(body: dict, selection: ModeSelection) -> dict:
    """Apply observed answer-mode switches to a deep copy of ``body``."""
    _validate(selection)
    result = deepcopy(body)
    deep = selection.answer is AnswerMode.DEEP
    result["option"]["need_deep_think"] = 1 if deep else 0
    result["ext"]["use_deep_think"] = "1" if deep else "0"
    return result


def prepare_prompt(prompt: str, selection: ModeSelection) -> str:
    """Add the canonical intent phrase used by the standard completion route."""
    _validate(selection)
    prefixes = {
        FunctionMode.IMAGE: "生成图片：",
        FunctionMode.WRITING: "帮我写作：",
    }
    if selection.function is FunctionMode.PPT:
        return (
            f"生成PPT：请围绕主题制作恰好5页，每页有不同的标题和具体内容，不用空白页凑数。"
            f"主题：{prompt}。最后导出pptx文件并提供下载链接。"
        )
    if selection.answer is AnswerMode.SEARCH:
        prefix = "请联网搜索并回答："
    else:
        prefix = prefixes.get(selection.function, "")
    return prompt if not prefix or prompt.startswith(prefix) else f"{prefix}{prompt}"

