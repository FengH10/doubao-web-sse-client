"""Minimal browser-free client for Doubao's SSE completion endpoint."""

from __future__ import annotations

from dataclasses import dataclass
import json
import random
import secrets
import time
import uuid
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

from curl_cffi import requests as curl_requests

from .abogus import ABogusOptions, RandomSource, sign_a_bogus
from .artifacts import (
    ArtifactDownloadError,
    ArtifactKind,
    download_artifact,
    extract_artifact_refs,
)
from .mstoken import DEFAULT_USER_AGENT
from .modes import DEFAULT_MODE, FunctionMode, ModeSelection, apply_mode, prepare_prompt


class DoubaoProtocolError(RuntimeError):
    """An error event returned by the Doubao streaming endpoint."""


def _content_block_text(blocks: object) -> str:
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        content = block.get("content")
        if not isinstance(content, dict):
            continue
        text_block = content.get("text_block")
        if isinstance(text_block, dict) and isinstance(text_block.get("text"), str):
            parts.append(text_block["text"])
    return "".join(parts)


def extract_response_text(raw_event: str) -> str:
    """Extract an assistant text delta from one Doubao SSE ``data`` value."""
    if not raw_event or raw_event == "[DONE]":
        return ""
    try:
        event = json.loads(raw_event)
    except json.JSONDecodeError as exc:
        raise DoubaoProtocolError(f"invalid SSE JSON: {exc}") from exc
    if not isinstance(event, dict):
        return ""
    if "error_code" in event:
        raise DoubaoProtocolError(
            f"{event.get('error_code')}: {event.get('error_msg', 'Doubao protocol error')}"
        )
    if isinstance(event.get("text"), str):
        return event["text"]
    content = event.get("content")
    if isinstance(content, dict):
        text = _content_block_text(content.get("content_block"))
        if text:
            return text
    pieces: list[str] = []
    for operation in event.get("patch_op", []) if isinstance(event.get("patch_op"), list) else []:
        if not isinstance(operation, dict):
            continue
        patch = operation.get("patch_value")
        if isinstance(patch, dict):
            pieces.append(_content_block_text(patch.get("content_block")))
    return "".join(pieces)


@dataclass(frozen=True)
class DoubaoSession:
    cookie: str
    device_id: str
    tea_uuid: str
    web_id: str
    web_tab_id: str
    ms_token: str
    fp: str
    room_id: str
    last_section_id: str = ""
    last_message_index: int = 0
    region: str = "HK"


class DoubaoClient:
    origin = "https://www.doubao.com"

    def __init__(self, session: DoubaoSession, *, user_agent: str = DEFAULT_USER_AGENT):
        self.session = session
        self.user_agent = user_agent
        self._last_section_id = session.last_section_id
        self._last_message_index = session.last_message_index

    def build_body(
        self,
        prompt: str,
        *,
        mode: ModeSelection | None = None,
        conversation_id: str | None = None,
        local_conversation_id: str | None = None,
        local_message_id: str | None = None,
        bot_id: str = "7338286299411103781",
    ) -> dict:
        conversation = conversation_id or self.session.room_id
        now_ms = int(time.time() * 1000)
        message_id = local_message_id or str(uuid.uuid1())
        selection = mode or DEFAULT_MODE
        body = {
            "client_meta": {
                "conversation_id": conversation,
                "bot_id": bot_id,
                "last_section_id": self._last_section_id,
                "last_message_index": self._last_message_index,
                "local_permissions": [
                    {"permission_name": "ACCESS_COARSE_LOCATION", "status": 3},
                    {"permission_name": "ACCESS_FINE_LOCATION", "status": 3},
                    {"permission_name": "ACCESS_BACKGROUND_LOCATION", "status": 3},
                ],
            },
            "messages": [
                {
                    "local_message_id": message_id,
                    "content_block": [
                        {
                            "block_type": 10000,
                            "content": {
                                "text_block": {
                                    "text": prepare_prompt(prompt, selection),
                                    "icon_url": "",
                                    "icon_url_dark": "",
                                    "summary": "",
                                },
                                "pc_event_block": "",
                            },
                            "block_id": str(uuid.uuid4()),
                            "parent_id": "",
                            "meta_info": [],
                            "extra_info": {},
                            "append_fields": [],
                        }
                    ],
                    "message_status": 0,
                }
            ],
            "option": {
                "send_message_scene": "",
                "create_time_ms": now_ms,
                "collect_id": "",
                "is_audio": False,
                "answer_with_suggest": False,
                "agent_mode": 2,
                "tts_switch": False,
                "need_deep_think": 0,
                "click_clear_context": False,
                "from_suggest": False,
                "is_regen": False,
                "is_replace": False,
                "is_from_click_option": False,
                "is_from_click_softlink": False,
                "disable_sse_cache": False,
                "select_text_action": "",
                "is_select_text": False,
                "resend_for_regen": False,
                "scene_type": 0,
                "unique_key": str(uuid.uuid4()),
                "start_seq": 0,
                "need_create_conversation": conversation == "0",
                "regen_query_id": [],
                "edit_query_id": [],
                "regen_instruction": "",
                "no_replace_for_regen": False,
                "message_from": 0,
                "shared_app_name": "",
                "shared_app_id": "",
                "sse_recv_event_options": {"support_chunk_delta": True},
                "support_lazy_fetch_stream": True,
                "is_ai_playground": False,
                "is_old_user": False,
                "general_task_param": {
                    "runtime_type": 0,
                    "agent_task_param": {},
                    "project_id": "",
                    "server_do_compare": True,
                },
                "recovery_option": {
                    "is_recovery": False,
                    "req_create_time_sec": now_ms // 1000,
                    "append_sse_event_scene": 0,
                },
                "message_storage_type": 0,
                "related_deleted_message_ids": {},
                "connector_info_list": [],
                "model_config": {
                    "model_item_key": "0",
                    "model_extra_params": {},
                    "reasoning_effort": 3,
                },
                "aggregate_params": {
                    "mention_skill_list": "[]",
                    "mention_plugin_list": "[]",
                    "mention_ext": "[{}]",
                    "conversation_mode": "",
                    "mode_id": "1",
                    "model_item_key": "0",
                    "agent_mode": "2",
                    "reasoning_effort": "3",
                    "provider_id": "",
                },
            },
            "user_context": [],
            "ext": {
                "agent_mode": "2",
                "use_deep_think": "0",
                "general_task_param": '{"runtime_type":0,"agent_task_param":{},"project_id":"","server_do_compare":true}',
                "collection_id": "",
                "is_finish": "1",
                "commerce_credit_config_enable": "0",
            },
        }
        result = apply_mode(body, selection)
        if selection.function is FunctionMode.IMAGE:
            result["chat_ability"] = {
                "ability_type": 3,
                "ability_param": json.dumps(
                    {
                        "ability_param": {
                            "model": "Seedream 5.5",
                            "ratio": "auto",
                            "transparent": "false",
                            "input_box_content": {
                                "user_input_content": prompt,
                                "reply_message_format": "生成图片：%s",
                            },
                        },
                        "ability_type": 1,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
            result["option"].pop("agent_mode", None)
            result["option"]["model_config"] = {
                "model_item_key": "",
                "model_extra_params": {},
            }
            result["option"]["aggregate_params"].update(
                {
                    "mode_id": "",
                    "model_item_key": "",
                    "agent_mode": "",
                    "reasoning_effort": "",
                }
            )
            result["option"]["queue_client_state"] = {
                "queue_enabled": True,
                "queue_is_empty": True,
                "queue_submit_mode": 2,
            }
            result["option"]["is_old_user"] = True
            result["ext"].pop("agent_mode", None)
            result["ext"].pop("use_deep_think", None)
            result["ext"]["answer_with_suggest"] = "0"
        return result

    @staticmethod
    def serialize_body(body: dict) -> str:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def _query_params(self) -> list[tuple[str, str]]:
        s = self.session
        return [
            ("aid", "497858"),
            ("device_id", s.device_id),
            ("device_platform", "web"),
            ("doubao_device_platform", "web"),
            ("doubao_pc_version", "3.43.3"),
            ("fp", s.fp),
            ("language", "zh"),
            ("pc_version", "3.43.3"),
            ("pkg_type", "release_version"),
            ("real_aid", "497858"),
            ("region", s.region),
            ("samantha_web", "1"),
            ("sys_region", s.region),
            ("tea_uuid", s.tea_uuid),
            ("tz_name", "Asia/Shanghai"),
            ("use-olympus-account", "1"),
            ("version_code", "20800"),
            ("web_id", s.web_id),
            ("web_platform", "browser"),
            ("web_tab_id", s.web_tab_id),
            ("msToken", s.ms_token),
        ]

    def build_signed_url(
        self,
        body_json: str,
        *,
        options: ABogusOptions | None = None,
        rng: RandomSource | None = None,
    ) -> str:
        query = urlencode(self._query_params())
        signing_options = options or ABogusOptions(user_agent=self.user_agent)
        signature = sign_a_bogus(query, body_json, options=signing_options, rng=rng)
        return f"{self.origin}/chat/completion?{query}&{urlencode({'a_bogus': signature})}"

    def headers(self) -> dict[str, str]:
        trace = f"04-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
        return {
            "Accept": "text/event-stream",
            "Agw-Js-Conv": "str, str",
            "Content-Type": "application/json",
            "Cookie": self.session.cookie,
            "Last-Event-Id": "undefined",
            "Origin": self.origin,
            "Referer": f"{self.origin}/chat/{self.session.room_id}",
            "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "User-Agent": self.user_agent,
            "X-Flow-Trace": trace,
        }

    def stream(
        self,
        prompt: str,
        *,
        mode: ModeSelection | None = None,
        timeout: float = 60.0,
    ) -> Iterable[str]:
        body = self.serialize_body(self.build_body(prompt, mode=mode))
        response = curl_requests.post(
            self.build_signed_url(body),
            data=body.encode("utf-8"),
            headers=self.headers(),
            impersonate="chrome136",
            stream=True,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise DoubaoProtocolError(f"HTTP {response.status_code}")
        for raw_line in response.iter_lines():
            line = (
                raw_line.decode("utf-8", errors="replace")
                if isinstance(raw_line, bytes)
                else raw_line
            ).strip()
            if line.startswith("data:"):
                yield line[5:].strip()

    def process_event(self, raw_event: str) -> str:
        """Update the conversation cursor and return an assistant text delta."""
        if raw_event and raw_event != "[DONE]":
            try:
                event = json.loads(raw_event)
            except json.JSONDecodeError:
                event = None
            if isinstance(event, dict):
                ack = event.get("ack_client_meta")
                if isinstance(ack, dict) and ack.get("section_id"):
                    self._last_section_id = str(ack["section_id"])
                for query in event.get("query_list", []) if isinstance(event.get("query_list"), list) else []:
                    if isinstance(query, dict) and query.get("message_index") is not None:
                        self._last_message_index = max(
                            self._last_message_index, int(query["message_index"])
                        )
                meta = event.get("meta")
                if isinstance(meta, dict):
                    if meta.get("section_id"):
                        self._last_section_id = str(meta["section_id"])
                    if meta.get("index_in_conv") is not None:
                        self._last_message_index = max(
                            self._last_message_index, int(meta["index_in_conv"])
                        )
                message = event.get("message")
                if isinstance(message, dict) and message.get("index_in_conv") is not None:
                    self._last_message_index = max(
                        self._last_message_index, int(message["index_in_conv"])
                    )
                finish = event.get("msg_finish_attr")
                if isinstance(finish, dict) and finish.get("badge_count") is not None:
                    self._last_message_index = max(
                        self._last_message_index, int(finish["badge_count"])
                    )
        return extract_response_text(raw_event)

    def stream_text(
        self,
        prompt: str,
        *,
        mode: ModeSelection | None = None,
        timeout: float = 60.0,
        artifact_root: Path | None = None,
    ) -> Iterable[str]:
        """Yield only assistant text while retaining state for the next question."""
        selection = mode or DEFAULT_MODE
        artifact_kind = {
            FunctionMode.IMAGE: ArtifactKind.IMAGE,
            FunctionMode.PPT: ArtifactKind.PPT,
        }.get(selection.function)
        seen_artifacts: set[str] = set()
        pending_image = None
        ppt_saved = False
        download_headers = self.headers() if artifact_root and artifact_kind else {}

        def save(ref):
            try:
                saved = download_artifact(ref, artifact_root, download_headers)
            except ArtifactDownloadError as exc:
                return f"\n产物下载失败：{exc}\n"
            label = "图片" if ref.kind is ArtifactKind.IMAGE else "PPT"
            return f"\n已保存{label}：{saved}\n"

        request_timeout = max(timeout, 300.0) if artifact_kind is ArtifactKind.PPT else timeout
        for raw_event in self.stream(prompt, mode=selection, timeout=request_timeout):
            text = self.process_event(raw_event)
            if text:
                yield text
            if artifact_root is None or artifact_kind is None:
                continue
            for ref in extract_artifact_refs(raw_event, artifact_kind):
                if ref.url in seen_artifacts:
                    continue
                seen_artifacts.add(ref.url)
                if artifact_kind is ArtifactKind.IMAGE:
                    pending_image = ref
                else:
                    result = save(ref)
                    if result.startswith("\n已保存PPT："):
                        ppt_saved = True
                    yield result

        if artifact_root is not None and pending_image is not None:
            yield save(pending_image)
        if artifact_root is not None and artifact_kind is ArtifactKind.PPT and not ppt_saved:
            yield "\n未收到可下载的 PPT 文件。\n"
