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


class ImageModel(str, Enum):
    SEEDREAM_5_5 = "Seedream 5.5"
    SEEDREAM_5_0_PRO = "Seedream 5.0 Pro"
    SEEDREAM_5_0_FLASH = "Seedream 5.0 Flash"
    SEEDREAM_4_5 = "Seedream 4.5"
    SEEDREAM_4_0 = "Seedream 4.0"


DEFAULT_IMAGE_MODEL = ImageModel.SEEDREAM_5_5


@dataclass(frozen=True)
class ModeSelection:
    function: FunctionMode
    answer: AnswerMode
    image_model: ImageModel | None = None

    def __post_init__(self) -> None:
        if self.function is FunctionMode.IMAGE and self.image_model is None:
            object.__setattr__(self, "image_model", DEFAULT_IMAGE_MODEL)
        elif self.function is not FunctionMode.IMAGE and self.image_model is not None:
            raise ValueError("只有图像生成模式可以选择图像模型")

    @property
    def label(self) -> str:
        base = f"{self.function.value}/{self.answer.value}"
        return f"{base}/{self.image_model.value}" if self.image_model else base


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


def available_image_models() -> tuple[ImageModel, ...]:
    return tuple(ImageModel)


def _validate(selection: ModeSelection) -> None:
    if not any(
        available.function is selection.function
        and available.answer is selection.answer
        for available in _AVAILABLE
    ):
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

