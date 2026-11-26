import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from doubao_sign.artifacts import ArtifactDownloadError
from doubao_sign.client import DoubaoClient, DoubaoSession
from doubao_sign.modes import (
    AnswerMode,
    FunctionMode,
    ModeSelection,
    UnsupportedModeCombination,
    apply_mode,
    available_combinations,
    prepare_prompt,
)


class ModePresetTests(unittest.TestCase):
    def make_client(self):
        return DoubaoClient(
            DoubaoSession(
                cookie="cookie",
                device_id="device",
                tea_uuid="tea",
                web_id="web",
                web_tab_id="tab",
                ms_token="token",
                fp="fp",
                room_id="room",
                last_section_id="section",
                last_message_index=9,
            )
        )

    def test_available_combinations_match_observed_protocol_boundaries(self):
        combinations = set(available_combinations())

        self.assertEqual(
            combinations,
            {
                ModeSelection(FunctionMode.CHAT, AnswerMode.FAST),
                ModeSelection(FunctionMode.CHAT, AnswerMode.DEEP),
                ModeSelection(FunctionMode.CHAT, AnswerMode.SEARCH),
                ModeSelection(FunctionMode.IMAGE, AnswerMode.FAST),
                ModeSelection(FunctionMode.PPT, AnswerMode.FAST),
                ModeSelection(FunctionMode.WRITING, AnswerMode.FAST),
            },
        )

    def test_deep_mode_applies_captured_switches_without_mutating_base(self):
        base = {
            "option": {"need_deep_think": 0, "aggregate_params": {"mode_id": "1"}},
            "ext": {"use_deep_think": "0"},
        }
        original = copy.deepcopy(base)

        result = apply_mode(
            base, ModeSelection(FunctionMode.CHAT, AnswerMode.DEEP)
        )

        self.assertEqual(result["option"]["need_deep_think"], 1)
        self.assertEqual(result["ext"]["use_deep_think"], "1")
        self.assertEqual(base, original)

    def test_unsupported_combination_fails_before_request_building(self):
        selection = ModeSelection(FunctionMode.IMAGE, AnswerMode.DEEP)

        with self.assertRaisesRegex(UnsupportedModeCombination, "图像生成/深度思考"):
            apply_mode({"option": {}, "ext": {}}, selection)

    def test_function_modes_use_canonical_intent_triggers(self):
        self.assertEqual(
            prepare_prompt("蓝色圆点", ModeSelection(FunctionMode.IMAGE, AnswerMode.FAST)),
            "生成图片：蓝色圆点",
        )
        self.assertEqual(
            prepare_prompt("季度总结", ModeSelection(FunctionMode.PPT, AnswerMode.FAST)),
            "生成PPT：请围绕主题制作恰好5页，每页有不同的标题和具体内容，不用空白页凑数。主题：季度总结。最后导出pptx文件并提供下载链接。",
        )
        self.assertEqual(
            prepare_prompt("产品介绍", ModeSelection(FunctionMode.WRITING, AnswerMode.FAST)),
            "帮我写作：产品介绍",
        )
        self.assertEqual(
            prepare_prompt("今日新闻", ModeSelection(FunctionMode.CHAT, AnswerMode.SEARCH)),
            "请联网搜索并回答：今日新闻",
        )

    def test_client_applies_mode_without_leaking_into_next_request(self):
        client = self.make_client()

        deep = client.build_body(
            "问题", mode=ModeSelection(FunctionMode.CHAT, AnswerMode.DEEP)
        )
        fast = client.build_body(
            "问题", mode=ModeSelection(FunctionMode.CHAT, AnswerMode.FAST)
        )

        self.assertEqual(deep["option"]["need_deep_think"], 1)
        self.assertEqual(fast["option"]["need_deep_think"], 0)
        self.assertEqual(deep["client_meta"]["last_message_index"], 9)
        self.assertEqual(fast["client_meta"]["last_message_index"], 9)

    def test_only_image_mode_uses_captured_seedream_5_5_ability(self):
        client = self.make_client()

        image = client.build_body(
            "蓝色圆点", mode=ModeSelection(FunctionMode.IMAGE, AnswerMode.FAST)
        )
        chat = client.build_body(
            "蓝色圆点", mode=ModeSelection(FunctionMode.CHAT, AnswerMode.FAST)
        )

        self.assertIn("chat_ability", image)
        self.assertEqual(image["chat_ability"]["ability_type"], 3)
        self.assertEqual(
            json.loads(image["chat_ability"]["ability_param"]),
            {
                "ability_param": {
                    "model": "Seedream 5.5",
                    "ratio": "auto",
                    "transparent": "false",
                    "input_box_content": {
                        "user_input_content": "蓝色圆点",
                        "reply_message_format": "生成图片：%s",
                    },
                },
                "ability_type": 1,
            },
        )
        self.assertNotIn("agent_mode", image["option"])
        self.assertEqual(
            image["option"]["model_config"],
            {"model_item_key": "", "model_extra_params": {}},
        )
        self.assertEqual(
            image["option"]["aggregate_params"],
            {
                "mention_skill_list": "[]",
                "mention_plugin_list": "[]",
                "mention_ext": "[{}]",
                "conversation_mode": "",
                "mode_id": "",
                "model_item_key": "",
                "agent_mode": "",
                "reasoning_effort": "",
                "provider_id": "",
            },
        )
        self.assertEqual(
            image["option"]["queue_client_state"],
            {
                "queue_enabled": True,
                "queue_is_empty": True,
                "queue_submit_mode": 2,
            },
        )
        self.assertTrue(image["option"]["is_old_user"])
        self.assertNotIn("agent_mode", image["ext"])
        self.assertNotIn("use_deep_think", image["ext"])
        self.assertEqual(image["ext"]["answer_with_suggest"], "0")
        self.assertNotIn("chat_ability", chat)
        self.assertFalse(chat["option"]["is_old_user"])
        self.assertEqual(chat["option"]["model_config"]["model_item_key"], "0")
        self.assertEqual(chat["ext"]["agent_mode"], "2")

    def test_ppt_stream_allows_longer_generation_time(self):
        client = self.make_client()
        calls = []
        def fake_stream(*args, **kwargs):
            calls.append(kwargs)
            return iter(())
        client.stream = fake_stream
        list(client.stream_text(
            "主题",
            mode=ModeSelection(FunctionMode.PPT, AnswerMode.FAST),
            timeout=60,
        ))
        self.assertGreaterEqual(calls[0]["timeout"], 300)

    def test_image_stream_downloads_repeated_artifact_once_and_yields_path(self):
        client = self.make_client()
        url = "https://cdn.example/result.png"
        client.stream = lambda *args, **kwargs: iter(
            [
                json.dumps({"image_url": url}),
                json.dumps({"preview_image_url": url}),
                json.dumps({"text": "生成完成"}, ensure_ascii=False),
            ]
        )
        mode = ModeSelection(FunctionMode.IMAGE, AnswerMode.FAST)
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            saved = (root / "images" / "result.png").resolve()
            with patch("doubao_sign.client.download_artifact", return_value=saved) as download:
                output = list(client.stream_text("画图", mode=mode, artifact_root=root))

        self.assertEqual(download.call_count, 1)
        self.assertIn("生成完成", output)
        self.assertIn(f"\n已保存图片：{saved}\n", output)

    def test_image_stream_saves_only_last_full_image(self):
        client = self.make_client()
        client.stream = lambda *args, **kwargs: iter(
            [
                json.dumps({"creations": [{"image": {
                    "image_ori": {"url": "https://cdn.example/first.png"},
                    "image_preview": {"url": "https://cdn.example/first-preview.png"},
                }}]}),
                json.dumps({"creations": [{"image": {
                    "image_ori": {"url": "https://cdn.example/final.png"},
                    "image_preview": {"url": "https://cdn.example/final-preview.png"},
                }}]}),
                json.dumps({"text": "生成完成"}, ensure_ascii=False),
            ]
        )
        mode = ModeSelection(FunctionMode.IMAGE, AnswerMode.FAST)
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            saved = (root / "images" / "final.png").resolve()
            with patch("doubao_sign.client.download_artifact", return_value=saved) as download:
                output = list(client.stream_text("画图", mode=mode, artifact_root=root))

        download.assert_called_once()
        self.assertEqual(download.call_args.args[0].url, "https://cdn.example/final.png")
        self.assertIn(f"\n已保存图片：{saved}\n", output)

    def test_ppt_stream_downloads_exported_pptx_file(self):
        client = self.make_client()
        url = "https://cdn.example/export.pptx"
        client.stream = lambda *args, **kwargs: iter(
            [json.dumps({"content": {"file_block": {
                "name": "演示.pptx", "url": url,
            }}})]
        )
        mode = ModeSelection(FunctionMode.PPT, AnswerMode.FAST)
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            saved = (root / "ppt" / "演示.pptx").resolve()
            with patch("doubao_sign.client.download_artifact", return_value=saved) as download:
                output = list(client.stream_text("做 PPT", mode=mode, artifact_root=root))

        download.assert_called_once()
        self.assertEqual(download.call_args.args[0].url, url)
        self.assertIn(f"\n已保存PPT：{saved}\n", output)

    def test_ppt_stream_reports_when_only_online_card_is_returned(self):
        client = self.make_client()
        client.stream = lambda *args, **kwargs: iter(
            [json.dumps({"text": "在线文稿已生成"}, ensure_ascii=False)]
        )
        mode = ModeSelection(FunctionMode.PPT, AnswerMode.FAST)
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            output = list(client.stream_text("做 PPT", mode=mode, artifact_root=Path(directory)))

        self.assertIn("在线文稿已生成", output)
        self.assertIn("\n未收到可下载的 PPT 文件。\n", output)

    def test_normal_mode_never_downloads_artifact_urls(self):
        client = self.make_client()
        client.stream = lambda *args, **kwargs: iter(
            [json.dumps({"image_url": "https://cdn.example/result.png"})]
        )
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            with patch("doubao_sign.client.download_artifact") as download:
                list(
                    client.stream_text(
                        "解释链接",
                        mode=ModeSelection(FunctionMode.CHAT, AnswerMode.FAST),
                        artifact_root=Path(directory),
                    )
                )

        download.assert_not_called()

    def test_download_error_does_not_suppress_later_text(self):
        client = self.make_client()
        client.stream = lambda *args, **kwargs: iter(
            [
                json.dumps({"presentation_url": "https://cdn.example/result.pptx"}),
                json.dumps({"text": "PPT 已生成"}, ensure_ascii=False),
            ]
        )
        mode = ModeSelection(FunctionMode.PPT, AnswerMode.FAST)
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            with patch(
                "doubao_sign.client.download_artifact",
                side_effect=ArtifactDownloadError("下载失败：HTTP 403"),
            ):
                output = list(
                    client.stream_text("做 PPT", mode=mode, artifact_root=Path(directory))
                )

        self.assertIn("\n产物下载失败：下载失败：HTTP 403\n", output)
        self.assertIn("PPT 已生成", output)


if __name__ == "__main__":
    unittest.main()
