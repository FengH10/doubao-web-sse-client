"""Extract and persist generated artifacts from Doubao SSE events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Callable, Mapping
from urllib.parse import urlsplit

from curl_cffi import requests as curl_requests


class ArtifactKind(str, Enum):
    IMAGE = "image"
    PPT = "ppt"


@dataclass(frozen=True)
class ArtifactRef:
    kind: ArtifactKind
    url: str
    filename: str | None = None


class ArtifactDownloadError(RuntimeError):
    """An artifact could not be downloaded or validated."""


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_PPT_EXTENSIONS = {".ppt", ".pptx"}
_FILENAME_KEYS = ("file_name", "filename", "name")
_CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def _extension(url: str) -> str:
    return PurePosixPath(urlsplit(url).path).suffix.lower()


def _typed_context(kind: ArtifactKind, keys: tuple[str, ...]) -> bool:
    joined = " ".join(keys).lower()
    if kind is ArtifactKind.IMAGE:
        return "image" in joined or "picture" in joined
    return any(token in joined for token in ("ppt", "presentation", "slide"))


def _is_artifact_url(url: str, kind: ArtifactKind, keys: tuple[str, ...]) -> bool:
    if urlsplit(url).scheme != "https":
        return False
    extension = _extension(url)
    if kind is ArtifactKind.IMAGE and extension in _IMAGE_EXTENSIONS:
        return _typed_context(kind, keys)
    if kind is ArtifactKind.PPT and extension in _PPT_EXTENSIONS:
        return True
    return _typed_context(kind, keys) and any(
        token in keys[-1].lower() for token in ("url", "download", "file")
    )


def extract_artifact_refs(
    raw_event: str, expected_kind: ArtifactKind
) -> tuple[ArtifactRef, ...]:
    """Return unique, typed artifact URLs from one raw SSE data value."""
    try:
        event = json.loads(raw_event)
    except (json.JSONDecodeError, TypeError):
        return ()

    refs: list[ArtifactRef] = []
    seen: set[str] = set()

    def visit(value: object, keys: tuple[str, ...], filename: str | None) -> None:
        if isinstance(value, dict):
            local_filename = next(
                (
                    str(value[key])
                    for key in _FILENAME_KEYS
                    if isinstance(value.get(key), str) and value[key].strip()
                ),
                filename,
            )
            if expected_kind is ArtifactKind.IMAGE and "image" in keys:
                variants = (
                    "image_ori",
                    "image_ori_raw",
                    "image_preview",
                    "image_preview_resize",
                    "image_thumb",
                )
                if any(variant in value for variant in variants):
                    for variant in ("image_ori", "image_ori_raw"):
                        image_data = value.get(variant)
                        if not isinstance(image_data, dict):
                            continue
                        url = image_data.get("url")
                        if isinstance(url, str) and _is_artifact_url(
                            url, expected_kind, (*keys, variant, "url")
                        ):
                            if url not in seen:
                                seen.add(url)
                                refs.append(ArtifactRef(expected_kind, url, local_filename))
                            return
                    return
            for key, nested in value.items():
                visit(nested, (*keys, str(key)), local_filename)
        elif isinstance(value, list):
            for nested in value:
                visit(nested, keys, filename)
        elif isinstance(value, str) and _is_artifact_url(value, expected_kind, keys):
            if value not in seen:
                seen.add(value)
                refs.append(ArtifactRef(expected_kind, value, filename))

    visit(event, (), None)
    return tuple(refs)


def _header(response: object, name: str) -> str:
    headers = getattr(response, "headers", {})
    return next(
        (str(value) for key, value in headers.items() if str(key).lower() == name.lower()),
        "",
    )


def _response_filename(response: object) -> str | None:
    disposition = _header(response, "content-disposition")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.I)
    return match.group(1).strip() if match else None


def _safe_filename(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.replace("\\", "/")
    result = PurePosixPath(normalized).name.strip().strip(".")
    return result or None


def _validated_extension(
    kind: ArtifactKind, content_type: str, candidate: str | None, content: bytes
) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    content_extension = _CONTENT_TYPE_EXTENSIONS.get(media_type)
    candidate_extension = Path(candidate).suffix.lower() if candidate else ""
    allowed = _IMAGE_EXTENSIONS if kind is ArtifactKind.IMAGE else _PPT_EXTENSIONS
    if content_extension in allowed:
        extension = content_extension
    elif candidate_extension in allowed:
        extension = candidate_extension
    else:
        raise ArtifactDownloadError("下载内容类型与生成模式不匹配")
    if kind is ArtifactKind.PPT and extension == ".pptx" and not content.startswith(b"PK"):
        raise ArtifactDownloadError("PPT 文件格式校验失败")
    return extension


def download_artifact(
    ref: ArtifactRef,
    output_root: Path,
    headers: Mapping[str, str],
    *,
    getter: Callable[..., object] = curl_requests.get,
) -> Path:
    """Download one authenticated artifact and atomically persist it."""
    try:
        response = getter(
            ref.url,
            headers=dict(headers),
            impersonate="chrome136",
            timeout=60,
        )
    except Exception as exc:
        raise ArtifactDownloadError(f"下载请求失败：{type(exc).__name__}") from exc
    status_code = int(getattr(response, "status_code", 0))
    if status_code >= 400 or status_code == 0:
        raise ArtifactDownloadError(f"下载失败：HTTP {status_code}")
    content = bytes(getattr(response, "content", b""))
    if not content:
        raise ArtifactDownloadError("下载失败：服务器返回空文件")

    suggested = _safe_filename(_response_filename(response)) or _safe_filename(ref.filename)
    extension = _validated_extension(
        ref.kind, _header(response, "content-type"), suggested, content
    )
    stem = Path(suggested).stem if suggested else "artifact"
    digest = hashlib.sha256(ref.url.encode("utf-8")).hexdigest()[:12]
    directory = Path(output_root).resolve() / ("images" if ref.kind is ArtifactKind.IMAGE else "ppt")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}{extension}"
    if target.exists():
        target = directory / f"{stem}-{digest}{extension}"
    temporary = target.with_suffix(f"{target.suffix}.part")
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ArtifactDownloadError(f"保存文件失败：{type(exc).__name__}") from exc
    return target.resolve()
