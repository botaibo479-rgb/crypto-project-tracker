import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import credentials


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)
        self.missing_local = patch.object(credentials, "LOCAL_ENV", self.path / "none")
        self.missing_local.start()

    def tearDown(self):
        self.missing_local.stop()
        self.dir.cleanup()

    def private(self, name, text, mode=0o600):
        path = self.path / name
        path.write_text(text)
        path.chmod(mode)
        return path

    def test_systemd_credential_wins(self):
        (self.path / "opennews_token").write_text("from-systemd\n")
        env = {"CREDENTIALS_DIRECTORY": self.dir.name, "OPENNEWS_TOKEN": "from-env"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                credentials.load("OPENNEWS_TOKEN", "opennews_token"), "from-systemd"
            )

    def test_file_then_environment(self):
        path = self.private("token", "from-file\n")
        with patch.dict(
            os.environ,
            {"OPENNEWS_TOKEN_FILE": str(path), "OPENNEWS_TOKEN": "from-env"},
            clear=True,
        ):
            self.assertEqual(credentials.load("OPENNEWS_TOKEN"), "from-file")
        with patch.dict(os.environ, {"OPENNEWS_TOKEN": "from-env"}, clear=True):
            self.assertEqual(credentials.load("OPENNEWS_TOKEN"), "from-env")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(credentials.load("OPENNEWS_TOKEN"), "")

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_group_readable_files_are_refused(self):
        path = self.private("token", "x", 0o644)
        with patch.dict(os.environ, {"OPENNEWS_TOKEN_FILE": str(path)}, clear=True):
            with self.assertRaises(PermissionError) as raised:
                credentials.load("OPENNEWS_TOKEN")
        self.assertNotIn("x\n", str(raised.exception))
        local = self.private(".env.local", "OPENNEWS_TOKEN=abc\n", 0o640)
        with self.assertRaises(PermissionError):
            credentials.dotenv(local)

    def test_dotenv_parses_quotes_and_comments(self):
        local = self.private(".env.local", "# c\nOPENNEWS_TOKEN='abc'\nX=\"1\"\n")
        self.assertEqual(credentials.dotenv(local), {"OPENNEWS_TOKEN": "abc", "X": "1"})

    def test_redact_and_fingerprint(self):
        text = (
            "GET /?token=abc123&x=1 Authorization: Bearer sk-live-XYZ and s3cr3tvalue"
        )
        clean = credentials.redact(text, ["s3cr3tvalue"])
        for secret in ["abc123", "sk-live-XYZ", "s3cr3tvalue"]:
            self.assertNotIn(secret, clean)
        self.assertEqual(len(credentials.fingerprint("abc")), 8)
        self.assertIsNone(credentials.fingerprint(""))


if __name__ == "__main__":
    unittest.main()
