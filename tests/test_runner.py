import json
from pathlib import Path
import unittest

from doubao_sign.client import (
    DoubaoClient,
    DoubaoProtocolError,
    DoubaoSession,
    extract_response_text,
)
from doubao_sign.console import run_console, select_mode
from doubao_sign.modes import DEFAULT_MODE, ImageModel, available_combinations


class ResponseParserTests(unittest.TestCase):
    def test_extracts_top_level_chunk_delta(self):
        self.assertEqual(extract_response_text('{"text":"你好"}'), "你好")

    def test_extracts_initial_assistant_content_block(self):
        event = {
            "content": {
                "content_block": [
                    {"block_type": 10000, "content": {"text_block": {"text": "Python"}}}
                ]
            }
        }
        self.assertEqual(extract_response_text(json.dumps(event)), "Python")

    def test_extracts_stream_patch_content_block(self):
        event = {
            "message_id": "1",
            "patch_op": [
                {
                    "patch_value": {
                        "content_block": [
                            {"content": {"text_block": {"text": "入口成功"}}}
                        ]
                    }
                }
            ],
        }
        self.assertEqual(extract_response_text(json.dumps(event)), "入口成功")

    def test_ignores_full_user_message_notification(self):
        event = {
            "message": {
                "user_type": 1,
                "content_block": [
                    {"content": {"text_block": {"text": "这是用户问题"}}}
                ],
            }
        }
        self.assertEqual(extract_response_text(json.dumps(event)), "")

    def test_raises_readable_protocol_error(self):
        with self.assertRaisesRegex(DoubaoProtocolError, "710022004.*rate limited"):
            extract_response_text(
                '{"error_code":710022004,"error_msg":"rate limited"}'
            )

    def test_ignores_done_and_non_text_events(self):
        self.assertEqual(extract_response_text("[DONE]"), "")
        self.assertEqual(extract_response_text('{"end_type":3}'), "")
        self.assertEqual(extract_response_text("{}"), "")


class ConversationStateTests(unittest.TestCase):
    def setUp(self):
        self.client = DoubaoClient(
            DoubaoSession(
                cookie="cookie",
                device_id="device",
                tea_uuid="tea",
                web_id="web",
                web_tab_id="tab",
                ms_token="token",
                fp="fp",
                room_id="conversation",
                last_section_id="section-1",
                last_message_index=15,
            )
        )

    def test_ack_and_reply_advance_next_request_cursor(self):
        ack = {
            "query_list": [{"message_index": 26}],
            "ack_client_meta": {"section_id": "section-2"},
        }
        self.assertEqual(self.client.process_event(json.dumps(ack)), "")
        reply = {
            "content": {
                "content_block": [
                    {"content": {"text_block": {"text": "回答"}}}
                ]
            },
            "meta": {"section_id": "section-2", "index_in_conv": 27},
        }
        self.assertEqual(self.client.process_event(json.dumps(reply)), "回答")
        body = self.client.build_body("下一问")
        self.assertEqual(body["client_meta"]["last_section_id"], "section-2")
        self.assertEqual(body["client_meta"]["last_message_index"], 27)


class FakeStreamingClient:
    def __init__(self):
        self.prompts = []
        self.artifact_roots = []

    def stream_text(self, prompt, *, mode=None, artifact_root=None):
        self.prompts.append((prompt, mode))
        self.artifact_roots.append(artifact_root)
        yield "答"
        yield "案"


class ConsoleTests(unittest.TestCase):
    def test_repeats_questions_until_exit(self):
        client = FakeStreamingClient()
        answers = iter(["第一问", "第二问", "退出"])
        output = []

        run_console(client, input_fn=lambda _: next(answers), output_fn=output.append)

        self.assertEqual(
            client.prompts,
            [("第一问", DEFAULT_MODE), ("第二问", DEFAULT_MODE)],
        )
        self.assertEqual("".join(output), "豆包> 答案\n豆包> 答案\n")

    def test_select_mode_reprompts_invalid_input(self):
        answers = iter(["x", "99", "2"])
        output = []

        selected = select_mode(
            input_fn=lambda _: next(answers), output_fn=output.append
        )

        self.assertEqual(selected, available_combinations()[1])
        self.assertIn("请输入 1-6", "".join(output))

    def test_selecting_image_mode_prompts_for_seedream_model(self):
        answers = iter(["4", "3"])
        output = []

        selected = select_mode(
            input_fn=lambda _: next(answers), output_fn=output.append
        )

        self.assertEqual(selected.function, available_combinations()[3].function)
        self.assertEqual(selected.image_model, ImageModel.SEEDREAM_5_0_FLASH)
        rendered = "".join(output)
        self.assertIn("可用图像模型", rendered)
        self.assertIn("3. Seedream 5.0 Flash", rendered)

    def test_runtime_commands_switch_mode_and_show_help(self):
        client = FakeStreamingClient()
        answers = iter(["/mode", "3", "今日新闻", "/modes", "/help", "退出"])
        output = []

        run_console(client, input_fn=lambda _: next(answers), output_fn=output.append)

        self.assertEqual(client.prompts, [("今日新闻", available_combinations()[2])])
        rendered = "".join(output)
        self.assertIn("已切换：普通对话/联网搜索（自动触发）", rendered)
        self.assertIn("/mode", rendered)
        self.assertIn("1. 普通对话/快速", rendered)

    def test_select_mode_returns_none_on_eof(self):
        def end(_: str) -> str:
            raise EOFError

        self.assertIsNone(select_mode(input_fn=end, output_fn=lambda _: None))

    def test_console_passes_artifact_root_to_stream(self):
        client = FakeStreamingClient()
        answers = iter(["生成一个图", "退出"])
        root = Path("outputs").resolve()

        run_console(
            client,
            artifact_root=root,
            input_fn=lambda _: next(answers),
            output_fn=lambda _: None,
        )

        self.assertEqual(client.artifact_roots, [root])


if __name__ == "__main__":
    unittest.main()
