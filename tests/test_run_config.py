import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run import resolve_session_file


class SessionFileResolutionTests(unittest.TestCase):
    def test_reads_saved_session_when_login_switch_is_off(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            saved = root / ".local" / "session.json"
            saved.parent.mkdir()
            saved.write_text("{}", encoding="utf-8")
            with patch("doubao_sign.login.scan_login") as login:
                self.assertEqual(
                    resolve_session_file(root, login_enabled=False), saved
                )
            login.assert_not_called()

    def test_login_switch_forces_fresh_scan(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            saved = root / ".local" / "session.json"
            saved.parent.mkdir()
            saved.write_text("{}", encoding="utf-8")
            with patch("doubao_sign.login.scan_login", return_value=saved) as login:
                self.assertEqual(resolve_session_file(root, login_enabled=True), saved)
            login.assert_called_once_with(saved)

    def test_missing_session_starts_scan_with_switch_off(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            saved = root / ".local" / "session.json"
            with patch("doubao_sign.login.scan_login", return_value=saved) as login:
                self.assertEqual(resolve_session_file(root, login_enabled=False), saved)
            login.assert_called_once_with(saved)


if __name__ == "__main__":
    unittest.main()
