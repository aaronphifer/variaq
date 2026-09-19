import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from variaq.errors import BackendUnavailableError, MissingOptionalDependency, ValidationError
from variaq.experiments.runner import ExperimentRunner
from variaq.experiments.storage import ExperimentStore
from variaq.models import SolverConfig, SolveStatus
from variaq.problems.maxcut import MaxCutProblem
from variaq.solvers.cudaq_qaoa import (
    CudaQQAOACpuSolver,
    CudaQQAOAGpuSolver,
    CudaQStatevectorBackend,
    _load_cudaq,
    _selected_target,
)
from variaq.solvers.qaoa_shared import generate_parameter_candidates
from variaq.solvers.qiskit_qaoa import QiskitStatevectorBackend, _load_quantum_dependencies


def cudaq_installed() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("cudaq") is not None
    except (ImportError, ValueError):
        return False


@unittest.skipUnless(cudaq_installed(), "optional CUDA-Q dependency is not installed")
class CudaQIntegrationTests(unittest.TestCase):
    def _backends(
        self, problem: MaxCutProblem, p: int
    ) -> tuple[QiskitStatevectorBackend, CudaQStatevectorBackend, object]:
        np, quantum_circuit, statevector = _load_quantum_dependencies()
        qiskit_backend = QiskitStatevectorBackend(problem, p, 42, np, quantum_circuit, statevector)
        cudaq = _load_cudaq()
        cudaq_backend = CudaQStatevectorBackend(cudaq, problem, p, 42)
        return qiskit_backend, cudaq_backend, cudaq

    def test_p1_expectations_match_analytic_sign_and_angle_convention(self) -> None:
        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        qiskit_backend, cudaq_backend, cudaq = self._backends(problem, 1)
        vectors = ((0.0, 0.0), (0.5, 0.25), (math.pi / 2, math.pi / 8))
        with _selected_target(cudaq, "qpp-cpu"):
            for gamma, beta in vectors:
                expected = 0.5 + 0.5 * math.sin(4.0 * beta) * math.sin(gamma)
                qiskit_value = qiskit_backend.expectation((gamma, beta))
                cudaq_value = cudaq_backend.expectation((gamma, beta))
                self.assertAlmostEqual(qiskit_value, expected, places=12)
                self.assertAlmostEqual(cudaq_value, expected, places=12)
        self.assertAlmostEqual(expected, 1.0, places=12)

    def test_p2_fixed_and_seeded_expectations_match(self) -> None:
        problem = MaxCutProblem.from_edges(4, [(0, 1), (1, 2), (2, 3), (0, 3), (0, 2, 0.5)])
        qiskit_backend, cudaq_backend, cudaq = self._backends(problem, 2)
        vectors = [
            (0.0, 0.0, 0.0, 0.0),
            (math.pi / 2, math.pi / 4, math.pi / 8, math.pi / 6),
            *generate_parameter_candidates(2, 3, 42),
        ]
        with _selected_target(cudaq, "qpp-cpu"):
            for vector in vectors:
                self.assertAlmostEqual(
                    qiskit_backend.expectation(vector),
                    cudaq_backend.expectation(vector),
                    places=10,
                )

    def test_cudaq_sample_bitstring_is_q0_first(self) -> None:
        cudaq = _load_cudaq()
        with _selected_target(cudaq, "qpp-cpu"):
            kernel = cudaq.make_kernel()
            qubits = kernel.qalloc(3)
            kernel.x(qubits[0])
            result = cudaq.sample(kernel, shots_count=16)
        self.assertEqual(dict(result.items()), {"100": 16})

    def test_cpu_solver_metadata_and_reproduction(self) -> None:
        problem = MaxCutProblem.from_edges(3, [(0, 1), (1, 2), (0, 2)])
        config = SolverConfig(
            seed=7,
            parameters={"p": 1, "optimizer_trials": 3, "shots": 64, "warmup": True},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ExperimentStore(Path(directory) / "runs.sqlite3")
            runner = ExperimentRunner(store)
            run = runner.run_one(problem, CudaQQAOACpuSolver(), config)
            reproduced = runner.reproduce(run.run_id)
        self.assertEqual(run.result.status, SolveStatus.SUCCESS)
        self.assertEqual(run.result.backend.name, "qpp-cpu")
        self.assertEqual(run.result.backend.metrics["framework"], "cudaq")
        self.assertEqual(run.result.backend.metrics["floating_point_precision"], "fp64")
        self.assertIn("candidate_parameter_digest", run.result.backend.metrics)
        self.assertIsNotNone(run.result.backend.metrics["warmup_seconds"])
        self.assertEqual(reproduced.rerun_of, run.run_id)
        self.assertEqual(reproduced.result.solver_name, "cudaq-cpu")
        self.assertNotEqual(reproduced.run_id, run.run_id)

    def test_cudaq_runtime_failure_is_recorded_as_failed(self) -> None:
        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        with tempfile.TemporaryDirectory() as directory:
            runner = ExperimentRunner(ExperimentStore(Path(directory) / "runs.sqlite3"))
            with mock.patch.object(
                CudaQStatevectorBackend,
                "expectation",
                side_effect=RuntimeError("intentional CUDA-Q failure"),
            ):
                run = runner.run_one(
                    problem,
                    CudaQQAOACpuSolver(),
                    SolverConfig(parameters={"optimizer_trials": 1, "shots": 8}),
                )
        self.assertEqual(run.result.status, SolveStatus.FAILED)
        self.assertIn("intentional CUDA-Q failure", run.result.errors[0])


class CudaQCapabilityTests(unittest.TestCase):
    def test_gpu_unavailable_is_not_a_failed_scientific_result(self) -> None:
        class NoGpuCudaQ:
            @staticmethod
            def has_target(name: str) -> bool:
                return True

            @staticmethod
            def num_available_gpus() -> int:
                return 0

        problem = MaxCutProblem.from_edges(2, [(0, 1)])
        with tempfile.TemporaryDirectory() as directory:
            runner = ExperimentRunner(ExperimentStore(Path(directory) / "runs.sqlite3"))
            with mock.patch("variaq.solvers.cudaq_qaoa._load_cudaq", return_value=NoGpuCudaQ()):
                run = runner.run_one(
                    problem,
                    CudaQQAOAGpuSolver(),
                    SolverConfig(parameters={"optimizer_trials": 1, "shots": 8}),
                )
        self.assertEqual(run.result.status, SolveStatus.UNAVAILABLE)
        self.assertFalse(run.result.feasible)
        self.assertEqual(run.result.errors, ())
        self.assertIn("no compatible NVIDIA GPU", run.result.warnings[0])

    def test_cpu_rejects_fp32_configuration(self) -> None:
        with self.assertRaisesRegex(ValidationError, "fp64"):
            CudaQQAOACpuSolver()._precision_and_target({"precision": "fp32"})

    def test_backend_unavailable_exception_carries_identity(self) -> None:
        error = BackendUnavailableError("missing", backend_name="nvidia", provider="cudaq")
        self.assertEqual(error.backend_name, "nvidia")
        self.assertEqual(error.provider, "cudaq")

    def test_z_missing_cudaq_dependency_error_is_actionable(self) -> None:
        if not cudaq_installed():
            self.skipTest("CUDA-Q is already absent; clean-install verification covers this path")
        with mock.patch.dict(sys.modules, {"cudaq": None}):
            with self.assertRaisesRegex(MissingOptionalDependency, r"\[cudaq\]"):
                _load_cudaq()


if __name__ == "__main__":
    unittest.main()
