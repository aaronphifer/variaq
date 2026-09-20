"""Runtime capability reporting for VariaQ CLI.

The ``capabilities`` command makes VariaQ authoritative about what it can do on
the current host. It distinguishes between *supported*, *installed*, and
*available* so that integrations can decide whether to attempt a solver.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from variaq import __version__
from variaq.errors import BackendUnavailableError
from variaq.serialization import OUTPUT_SCHEMA_VERSION, StructuredWarning
from variaq.solvers.base import get_solver, solver_names, solver_supported_families


@dataclass(frozen=True, slots=True)
class CapabilityEntry:
    name: str
    supported: bool
    installed: bool
    available: bool
    supported_families: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "supported": self.supported,
            "installed": self.installed,
            "available": self.available,
            "supported_families": list(self.supported_families),
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True, slots=True)
class FrameworkInfo:
    name: str
    version: str | None
    installed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "installed": self.installed,
        }


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _solver_capability(name: str) -> CapabilityEntry:
    supported = name in solver_names()
    installed = False
    available = False
    reason: str | None = None
    try:
        solver = get_solver(name)
        installed = True
        # Use a tiny synthetic problem to test availability without heavy work.
        if name in {"qaoa", "cudaq-cpu", "cudaq-gpu"}:
            from variaq.models import SolverConfig
            from variaq.problems.maxcut import MaxCutProblem

            try:
                solver.solve(
                    MaxCutProblem.from_edges(2, [(0, 1)]),
                    SolverConfig(seed=0, parameters={"optimizer_trials": 1, "shots": 1}),
                )
                available = True
            except BackendUnavailableError as exc:
                reason = str(exc)
            except Exception as exc:
                # Missing dependency / limit / runtime problem means installed but
                # not available for this environment.
                reason = f"{type(exc).__name__}: {exc}"
        else:
            available = True
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    return CapabilityEntry(
        name=name,
        supported=supported,
        installed=installed,
        available=available,
        supported_families=tuple(sorted(solver_supported_families(name))),
        reason=reason,
    )


def _cudaq_targets() -> dict[str, Any]:
    cudaq_version = _package_version("cudaq")
    if cudaq_version is None:
        return {
            "installed": False,
            "version": None,
            "qpp_cpu_available": False,
            "nvidia_available": False,
            "gpu_count": None,
            "reason": "CUDA-Q is not installed",
        }
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="cudaq-logical is in preview.*")
            warnings.filterwarnings(
                "ignore", message="The CUDA-Q `sample` and `observe` algorithmic primitives.*"
            )
            import cudaq
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        return {
            "installed": True,
            "version": cudaq_version,
            "qpp_cpu_available": False,
            "nvidia_available": False,
            "gpu_count": None,
            "reason": f"CUDA-Q import failed: {exc}",
        }
    qpp_cpu = bool(cudaq.has_target("qpp-cpu"))
    nvidia = bool(cudaq.has_target("nvidia"))
    gpu_count: int | None = None
    reason: str | None = None
    if nvidia:
        try:
            gpu_count = int(cudaq.num_available_gpus())
            if gpu_count < 1:
                nvidia = False
                reason = "CUDA-Q NVIDIA target present but reports no compatible GPU"
            else:
                reason = None
        except Exception as exc:
            nvidia = False
            gpu_count = None
            reason = f"Could not determine GPU availability: {exc}"
    return {
        "installed": True,
        "version": cudaq_version,
        "qpp_cpu_available": qpp_cpu,
        "nvidia_available": nvidia,
        "gpu_count": gpu_count,
        "reason": reason,
    }


def gather_capabilities() -> dict[str, Any]:
    qiskit_version = _package_version("qiskit")
    cudaq_info = _cudaq_targets()
    physical_qpu: dict[str, Any] = {
        "supported": False,
        "installed": False,
        "available": False,
        "reason": "Physical QPU execution is not supported in this release.",
    }
    warnings: list[StructuredWarning] = []
    if qiskit_version is None:
        warnings.append(
            StructuredWarning(
                type="optional_dependency_missing",
                message="Qiskit is not installed; the qaoa solver is unavailable",
            )
        )
    if not cudaq_info["installed"]:
        warnings.append(
            StructuredWarning(
                type="optional_dependency_missing",
                message="CUDA-Q is not installed; cudaq-cpu and cudaq-gpu are unavailable",
            )
        )
    elif cudaq_info["reason"] is not None:
        warnings.append(
            StructuredWarning(
                type="backend_availability",
                message=cudaq_info["reason"],
            )
        )
    return {
        "variaq": {
            "version": __version__,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "python_version": sys.version,
            "python_implementation": sys.implementation.name,
        },
        "problem_families": [
            {"name": "maxcut", "supported": True},
            {"name": "assignment", "supported": True},
            {"name": "subset-selection", "supported": True},
            {"name": "graph-partition", "supported": True},
        ],
        "solvers": [_solver_capability(name).to_dict() for name in solver_names()],
        "frameworks": [
            FrameworkInfo(
                name="qiskit", version=qiskit_version, installed=qiskit_version is not None
            ).to_dict(),
            {
                "name": "cudaq",
                "version": cudaq_info["version"],
                "installed": cudaq_info["installed"],
                "targets": {
                    "qpp_cpu": {
                        "installed": cudaq_info["installed"],
                        "available": cudaq_info["qpp_cpu_available"],
                    },
                    "nvidia": {
                        "installed": cudaq_info["installed"],
                        "available": cudaq_info["nvidia_available"],
                        "gpu_count": cudaq_info["gpu_count"],
                    },
                },
            },
        ],
        "physical_qpu": physical_qpu,
        "warnings": [warning.to_dict() for warning in warnings],
    }


def render_capabilities_human(data: dict[str, Any]) -> str:
    lines: list[str] = [
        f"VariaQ {data['variaq']['version']} (schema {data['variaq']['output_schema_version']})"
    ]
    lines.append(f"Python: {data['variaq']['python_version'].split()[0]}")
    lines.append("")
    lines.append("Problem families:")
    for family in data["problem_families"]:
        status = "supported" if family["supported"] else "unsupported"
        lines.append(f"  {family['name']}: {status}")
    lines.append("")
    lines.append("Solvers:")
    for solver in data["solvers"]:
        tags = [key for key in ("supported", "installed", "available") if solver.get(key)]
        tag_text = ", ".join(tags) if tags else "unsupported"
        families = ", ".join(solver.get("supported_families", []))
        line = f"  {solver['name']}: {tag_text} ({families})"
        if solver.get("reason"):
            line += f" ({solver['reason']})"
        lines.append(line)
    lines.append("")
    lines.append("Frameworks:")
    for framework in data["frameworks"]:
        version = framework.get("version") or "not installed"
        lines.append(f"  {framework['name']}: {version}")
    lines.append("")
    lines.append("Physical QPU: not supported in this release")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class CapabilitiesResult:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.data
