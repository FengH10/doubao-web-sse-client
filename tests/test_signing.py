import json
import random
import unittest

from doubao_sign.abogus import ABogusOptions, sign_a_bogus, sm3
from doubao_sign.client import DoubaoClient, DoubaoSession
from doubao_sign.mstoken import build_token_payload, extract_ms_token


class SigningTests(unittest.TestCase):
    def test_sm3_official_abc_vector(self):
        self.assertEqual(
            sm3(b"abc").hex(),
            "66c7f0f462eeedd9d1f2d46bdc10e4e2"
            "4167c4875cf2f7a2297da02b8f4ba8e0",
        )

    def test_a_bogus_is_reproducible_with_fixed_inputs(self):
        options = ABogusOptions(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            now_ms=1788091256878,
            ink_ms=1788091256877,
            biweekly_index=56,
            inner_width=1280,
            inner_height=720,
            outer_width=1280,
            outer_height=800,
            avail_width=1920,
            avail_height=1040,
            screen_width=1920,
            screen_height=1080,
            platform="Win32",
        )
        value = sign_a_bogus(
            "aid=497858&device_platform=web&msToken=test-token",
            json.dumps({"messages": [{"content": "你好"}]}, ensure_ascii=False, separators=(",", ":")),
            options=options,
            rng=random.Random(12345),
        )
        self.assertEqual(
            value,
            "YjUfDqyEm2AbPVMGmCcPybMRr68MNpSy5l4xmkN5eoKALZ0Y0clRTTPY"
            "Gozu4OOLKmkTieV7Ff0yYDVaZm355InkumkkuZzWm0/CVzfo2qNVa0isE"
            "NDZCh8zLwBbMbTLaA94i1v56sMeIDOW9HChABQHF/lrR5EdPN3GV2znE"
            "9K40AWjho2Ca5iBuhv2",
        )

    def test_mstoken_payload_is_protocol_data_not_random_token(self):
        payload = build_token_payload("fingerprint-data", now_ms=1700000000123)
        self.assertEqual(
            payload,
            {
                "magic": 0x20200422,
                "version": 1,
                "dataType": 8,
                "strData": "fingerprint-data",
                "tspFromClient": 1700000000123,
                "ulr": 0,
            },
        )

    def test_extract_mstoken_from_set_cookie(self):
        headers = [
            "sessionid=ignored; Path=/; HttpOnly",
            "msToken=abc_DEF-123; Domain=.bytedance.com; Path=/; Secure",
        ]
        self.assertEqual(extract_ms_token(headers), "abc_DEF-123")

    def test_client_builds_compact_body_and_signed_url(self):
        session = DoubaoSession(
            cookie="sessionid=test",
            device_id="7702366659906536979",
            tea_uuid="7702366653691283007",
            web_id="7702366653691283007",
            web_tab_id="436a47f3-c6b8-45dc-b462-e43c0613182e",
            ms_token="test-token",
            fp="verify_test",
            room_id="38450535984351746",
            last_section_id="38450535984351799",
            last_message_index=15,
        )
        client = DoubaoClient(session)
        body = client.build_body(
            "你好",
            conversation_id="38450535984351746",
            local_conversation_id="local_test",
            local_message_id="message-test",
        )
        body_json = client.serialize_body(body)
        self.assertNotIn('"bot_id": ', body_json)
        self.assertNotIn("completion_option", body)
        self.assertEqual(body["client_meta"]["last_message_index"], 15)
        self.assertEqual(
            body["messages"][0]["content_block"][0]["content"]["text_block"]["text"],
            "你好",
        )
        url = client.build_signed_url(
            body_json,
            options=ABogusOptions(
                user_agent=client.user_agent,
                now_ms=1788091256878,
                ink_ms=1788091256877,
                biweekly_index=56,
            ),
            rng=random.Random(7),
        )
        self.assertIn("msToken=test-token", url)
        self.assertIn("a_bogus=", url)
        self.assertEqual(url.count("a_bogus="), 1)


if __name__ == "__main__":
    unittest.main()
