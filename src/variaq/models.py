from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from importlib import metadata
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    return f"run-{uuid4()}"


class SolveStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class OptimizationSense(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True, slots=True)
class Evaluation:
    objective: float | None
    feasible: bool
    constraint_violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "feasible": self.feasible,
            "constraint_violations": list(self.constraint_violations),
        }


@dataclass(frozen=True, slots=True)
class SolverConfig:
    seed: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"seed": self.seed, "parameters": self.parameters}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SolverConfig:
        return cls(seed=int(value["seed"]), parameters=dict(value.get("parameters", {})))


@dataclass(frozen=True, slots=True)
class BackendMetadata:
    backend_type: str
    name: str
    provider: str
    is_local: bool
    versions: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    reproducibility_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_type": self.backend_type,
            "name": self.name,
            "provider": self.provider,
            "is_local": self.is_local,
            "versions": self.versions,
            "metrics": self.metrics,
            "reproducibility_notes": list(self.reproducibility_notes),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BackendMetadata:
        return cls(
            backend_type=value["backend_type"],
            name=value["name"],
            provider=value["provider"],
            is_local=bool(value["is_local"]),
            versions=dict(value.get("versions", {})),
            metrics=dict(value.get("metrics", {})),
            reproducibility_notes=tuple(value.get("reproducibility_notes", [])),
        )


@dataclass(frozen=True, slots=True)
class SolveResult:
    solver_name: str
    solver_version: str
    problem_id: str
    problem_type: str
    variable_count: int
    solution: tuple[int, ...] | None
    objective: float | None
    feasible: bool
    constraint_violations: tuple[str, ...]
    wall_time_seconds: float
    solver_time_seconds: float | None
    backend: BackendMetadata
    seed: int
    parameters: dict[str, Any]
    timestamp: str
    status: SolveStatus
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    best_known_objective: float | None = None
    best_known_source: str | None = None
    optimality_gap_percent: float | None = None
    approximation_ratio: float | None = None
    normalized_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "solver_name": self.solver_name,
            "solver_version": self.solver_version,
            "problem_id": self.problem_id,
            "problem_type": self.problem_type,
            "variable_count": self.variable_count,
            "solution": list(self.solution) if self.solution is not None else None,
            "objective": self.objective,
            "feasible": self.feasible,
            "constraint_violations": list(self.constraint_violations),
            "wall_time_seconds": self.wall_time_seconds,
            "solver_time_seconds": self.solver_time_seconds,
            "backend": self.backend.to_dict(),
            "seed": self.seed,
            "parameters": self.parameters,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "best_known_objective": self.best_known_objective,
            "best_known_source": self.best_known_source,
            "optimality_gap_percent": self.optimality_gap_percent,
            "approximation_ratio": self.approximation_ratio,
            "normalized_score": self.normalized_score,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SolveResult:
        solution = value.get("solution")
        return cls(
            solver_name=value["solver_name"],
            solver_version=value["solver_version"],
            problem_id=value["problem_id"],
            problem_type=value["problem_type"],
            variable_count=int(value["variable_count"]),
            solution=tuple(solution) if solution is not None else None,
            objective=value.get("objective"),
            feasible=bool(value["feasible"]),
            constraint_violations=tuple(value.get("constraint_violations", [])),
            wall_time_seconds=float(value["wall_time_seconds"]),
            solver_time_seconds=value.get("solver_time_seconds"),
            backend=BackendMetadata.from_dict(value["backend"]),
            seed=int(value["seed"]),
            parameters=dict(value.get("parameters", {})),
            timestamp=value["timestamp"],
            status=SolveStatus(value["status"]),
            warnings=tuple(value.get("warnings", [])),
            errors=tuple(value.get("errors", [])),
            best_known_objective=value.get("best_known_objective"),
            best_known_source=value.get("best_known_source"),
            optimality_gap_percent=value.get("optimality_gap_percent"),
            approximation_ratio=value.get("approximation_ratio"),
            normalized_score=value.get("normalized_score"),
        )


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    run_id: str
    benchmark_id: str | None
    created_at: str
    problem: dict[str, Any]
    solver_config: SolverConfig
    result: SolveResult
    environment: dict[str, Any]
    rerun_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "benchmark_id": self.benchmark_id,
            "created_at": self.created_at,
            "problem": self.problem,
            "solver_config": self.solver_config.to_dict(),
            "result": self.result.to_dict(),
            "environment": self.environment,
            "rerun_of": self.rerun_of,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExperimentRun:
        return cls(
            run_id=value["run_id"],
            benchmark_id=value.get("benchmark_id"),
            created_at=value["created_at"],
            problem=dict(value["problem"]),
            solver_config=SolverConfig.from_dict(value["solver_config"]),
            result=SolveResult.from_dict(value["result"]),
            environment=dict(value.get("environment", {})),
            rerun_of=value.get("rerun_of"),
        )


def capture_environment() -> dict[str, Any]:
    package_names = (
        "variaq",
        "qiskit",
        "qiskit-aer",
        "qiskit-ibm-runtime",
        "cudaq",
        "cuda-quantum-cu13",
        "numpy",
        "scipy",
    )
    packages: dict[str, str | None] = {}
    for package_name in package_names:
        try:
            packages[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            packages[package_name] = None
    return {
        "python": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": packages,
    }
