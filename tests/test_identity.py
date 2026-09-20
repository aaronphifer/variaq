import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

import variaq
from variaq.cli import main


class PublicIdentityTests(unittest.TestCase):
    def test_variaq_import_and_version(self) -> None:
        self.assertEqual(variaq.__version__, "0.4.1")

    def test_module_help_uses_public_cli_name(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "variaq", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: variaq"))
        self.assertIn("compare", result.stdout)

    def test_main_help_exits_successfully(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
