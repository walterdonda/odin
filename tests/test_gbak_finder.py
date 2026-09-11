import unittest
from unittest.mock import patch

from odin.gbak_finder import find_gbak


class TestGbakFinder(unittest.TestCase):
    @patch("os.path.exists")
    @patch("sys.platform", "win32")
    def test_find_gbak_windows_success(self, mock_exists):
        # Simulate finding gbak in a common Windows path
        mock_exists.return_value = True

        with patch.dict("os.environ", {"PATH": "C:\\Program Files\\Firebird\\bin"}):
            found = find_gbak()

        self.assertIsNotNone(found)
        self.assertTrue(str(found).endswith("gbak.exe"))

    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_find_gbak_linux_success(self, mock_exists):
        # Simulate finding gbak in a common Linux path
        mock_exists.side_effect = lambda path: str(path) == "/usr/bin/gbak"

        with patch.dict("os.environ", {"PATH": "/usr/bin"}):
            found = find_gbak()

        self.assertEqual(str(found), "/usr/bin/gbak")

    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_find_gbak_not_found(self, mock_exists):
        mock_exists.return_value = False

        with patch.dict("os.environ", {"PATH": "/usr/local/bin"}):
            found = find_gbak()

        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
