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

    def test_solver_supported_families_matrix(self) -> None:
        """supported_families is a static solver property, independent of backend availability."""
        for name, expected in (
            ("exact", {"maxcut", "assignment", "subset-selection", "graph-partition"}),
            ("heuristic", {"maxcut", "assignment", "subset-selection", "graph-partition"}),
            ("qaoa", {"maxcut", "assignment", "subset-selection"}),
            ("cudaq-cpu", {"maxcut", "assignment", "subset-selection"}),
            ("cudaq-gpu", {"maxcut", "assignment", "subset-selection"}),
        ):
            with self.subTest(name=name):
                entry = _solver_capability(name)
                self.assertEqual(set(entry.supported_families), expected)

    def test_solver_supported_families_present_when_backend_unavailable(self) -> None:
        """Families do not disappear just because a backend is not available."""
        with mock.patch("variaq.solvers.qiskit_qaoa._load_quantum_dependencies") as load:
            load.side_effect = ImportError("simulated missing qiskit")
            entry = _solver_capability("qaoa")
        self.assertEqual(
            set(entry.supported_families),
            {"maxcut", "assignment", "subset-selection"},
        )
        self.assertFalse(entry.available)

    def test_physical_qpu_reason_has_no_stale_version(self) -> None:
        data = gather_capabilities()
        reason = data["physical_qpu"]["reason"]
        self.assertNotIn("0.3.0", reason)
        self.assertIn("not supported", reason.lower())


if __name__ == "__main__":
    unittest.main()
