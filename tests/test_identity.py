import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import variaq
from variaq.cli import main


def _project_version() -> str:
    """Read the authoritative version from pyproject.toml."""
    repo_root = Path(__file__).resolve().parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    for line in pyproject_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("version not found in pyproject.toml")


class PublicIdentityTests(unittest.TestCase):
    def test_variaq_import_and_version(self) -> None:
        self.assertEqual(variaq.__version__, "0.5.0")

    def test_package_version_matches_pyproject(self) -> None:
        self.assertEqual(variaq.__version__, _project_version())

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
