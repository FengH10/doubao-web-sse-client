import json
import re
import unittest
from unittest.mock import patch

from doubao_sign.client import DoubaoClient, DoubaoSession


class FakeResponse:
    status_code = 200

    def iter_lines(self):
        yield b'data: {"text":"ok"}'
        yield b'data: [DONE]'


class BrowserTransportTests(unittest.TestCase):
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
                last_section_id="section",
                last_message_index=1,
            )
        )

    def test_headers_match_current_chrome_request_shape(self):
        headers = self.client.headers()
        self.assertIn("Chrome/136.0.0.0", headers["User-Agent"])
        self.assertEqual(headers["Agw-Js-Conv"], "str, str")
        self.assertEqual(headers["Last-Event-Id"], "undefined")
        self.assertEqual(headers["Sec-Ch-Ua-Mobile"], "?0")
        self.assertEqual(headers["Sec-Ch-Ua-Platform"], '"Windows"')
        self.assertRegex(
            headers["X-Flow-Trace"],
            r"^04-[0-9a-f]{32}-[0-9a-f]{16}-01$",
        )

    def test_stream_uses_chrome136_impersonation(self):
        with patch("doubao_sign.client.curl_requests.post", return_value=FakeResponse()) as post:
            events = list(self.client.stream("你好"))

        self.assertEqual(events, ['{"text":"ok"}', "[DONE]"])
        _, kwargs = post.call_args
        self.assertEqual(kwargs["impersonate"], "chrome136")
        self.assertTrue(kwargs["stream"])
        self.assertIsInstance(kwargs["data"], bytes)
        self.assertEqual(json.loads(kwargs["data"])["messages"][0]["content_block"][0]["content"]["text_block"]["text"], "你好")


if __name__ == "__main__":
    unittest.main()
