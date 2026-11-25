import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlencode

from doubao_sign.login import (
    LoginError,
    _completion_request,
    _logged_in,
    build_session,
    save_session,
)


def log(method, params):
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


class LoginCaptureTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://www.doubao.com/chat/completion?" + urlencode(
            {
                "device_id": "111",
                "tea_uuid": "222",
                "web_id": "333",
                "web_tab_id": "tab",
                "msToken": "token",
                "fp": "verify_fp",
                "region": "HK",
            }
        )

    def test_captures_completion_and_exact_cookie_header(self):
        logs = [
            log("Network.requestWillBeSentExtraInfo", {
                "requestId": "req-1", "headers": {"Cookie": "sessionid=private; sid_guard=private"}
            }),
            log("Network.requestWillBeSent", {
                "requestId": "req-1", "request": {"url": self.url}
            }),
        ]
        self.assertEqual(
            _completion_request(logs),
            (self.url, "sessionid=private; sid_guard=private"),
        )

    def test_builds_complete_session_without_revealing_cookie(self):
        session = build_session(self.url, "sessionid=private; sid_guard=private", "12345")
        self.assertEqual(session.device_id, "111")
        self.assertEqual(session.room_id, "12345")
        self.assertEqual(session.ms_token, "token")

    def test_rejects_missing_request_parameter(self):
        with self.assertRaisesRegex(LoginError, "msToken"):
            build_session(self.url.replace("msToken=token&", ""), "sessionid=x", "123")

    def test_recognizes_real_login_cookie(self):
        self.assertTrue(_logged_in([
            {"domain": ".doubao.com", "name": "sessionid"},
            {"domain": ".doubao.com", "name": "sid_guard"},
        ]))
        self.assertFalse(_logged_in([
            {"domain": ".doubao.com", "name": "flow_cur_user_sec_id"}
        ]))

    def test_saves_session_only_to_requested_file(self):
        session = build_session(self.url, "sessionid=private", "12345")
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "session.json"
            save_session(session, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["room_id"], "12345")
            self.assertEqual(saved["cookie"], "sessionid=private")
            self.assertFalse(path.with_name("session.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
