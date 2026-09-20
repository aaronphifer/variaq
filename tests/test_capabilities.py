"""Tests for the capabilities command and runtime availability semantics."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from variaq.capabilities import _cudaq_targets, _solver_capability, gather_capabilities
from variaq.cli import main


class CapabilityTests(unittest.TestCase):
    def test_gather_capabilities_includes_schema_version(self) -> None:
        data = gather_capabilities()
        self.assertEqual(data["variaq"]["output_schema_version"], "1")
        self.assertIn("version", data["variaq"])
        self.assertIn("python_version", data["variaq"])

    def test_gather_capabilities_lists_all_solvers(self) -> None:
        data = gather_capabilities()
        names = {solver["name"] for solver in data["solvers"]}
        self.assertTrue({"exact", "heuristic", "qaoa", "cudaq-cpu", "cudaq-gpu"} <= names)

    def test_solver_capability_distinguishes_supported_installed_available(self) -> None:
        entry = _solver_capability("exact")
        self.assertTrue(entry.supported)
        self.assertTrue(entry.installed)
        self.assertTrue(entry.available)
        self.assertIsNone(entry.reason)

    def test_missing_cudaq_reports_not_installed(self) -> None:
        with mock.patch("importlib.metadata.version", return_value=None):
            info = _cudaq_targets()
        self.assertFalse(info["installed"])
        self.assertIn("not installed", info["reason"])

    def test_capabilities_json_command(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["capabilities", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["command"], "capabilities")
        self.assertEqual(parsed["status"], "success")
        self.assertIn("solvers", parsed["data"])

    def test_capabilities_human_command(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["capabilities"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("VariaQ", text)
        self.assertIn("exact:", text)
        self.assertIn("Physical QPU", text)

    def test_physical_qpu_not_supported(self) -> None:
        data = gather_capabilities()
        self.assertFalse(data["physical_qpu"]["supported"])
        self.assertFalse(data["physical_qpu"]["available"])


if __name__ == "__main__":
    unittest.main()
