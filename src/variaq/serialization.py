"""Versioned, deterministic JSON serialization for VariaQ CLI output.

This module defines the public machine-readable envelope used by VariaQ's
command-line interface. The output schema is versioned independently of the
VariaQ package version. Consumers should treat schema version "1" as the
baseline introduced in VariaQ 0.3.0.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

OUTPUT_SCHEMA_VERSION = "1"


def safe_json_value(value: Any) -> Any:
    """Normalize a value into JSON-safe primitives.

    Recursively converts common non-JSON types (NumPy scalars, sets, paths,
    enums, finite-float checks) without dropping scientific precision. Raises
    ``TypeError`` for values that cannot be made JSON-safe so that serialization
    errors are explicit rather than producing invalid JSON.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, bool):  # bool is a subclass of int; already handled above
            return value
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeError(f"Non-finite float cannot be serialized: {value}")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [safe_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): safe_json_value(item) for key, item in value.items()}
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    # NumPy scalar / array support without requiring numpy at import time.
    numpy_type = type(value).__module__
    if numpy_type is not None and numpy_type.startswith("numpy"):
        if hasattr(value, "tolist"):
            return safe_json_value(value.tolist())
        if hasattr(value, "item"):
            return safe_json_value(value.item())
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    if hasattr(value, "__fspath__"):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__!r} is not JSON serializable")


@dataclass(frozen=True, slots=True)
class StructuredError:
    type: str
    message: str
    run_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    retryable: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "message": self.message,
        }
        if self.run_id is not None:
            result["run_id"] = self.run_id
        if self.context:
            result["context"] = safe_json_value(self.context)
        if self.retryable is not None:
            result["retryable"] = self.retryable
        return result


@dataclass(frozen=True, slots=True)
class StructuredWarning:
    type: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type, "message": self.message}
        if self.context:
            result["context"] = safe_json_value(self.context)
        return result


@dataclass(frozen=True, slots=True)
class Envelope:
    command: str
    status: str
    data: Any
    schema_version: str = OUTPUT_SCHEMA_VERSION
    warnings: tuple[StructuredWarning, ...] = ()
    error: StructuredError | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "command": self.command,
            "status": self.status,
            "data": safe_json_value(self.data),
        }
        if self.warnings:
            result["warnings"] = [warning.to_dict() for warning in self.warnings]
        if self.error is not None:
            result["error"] = self.error.to_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=None, sort_keys=True)


def success_envelope(command: str, data: Any, warnings: tuple[StructuredWarning, ...] = ()) -> str:
    return Envelope(command=command, status="success", data=data, warnings=warnings).to_json()


def error_envelope(
    command: str,
    error: StructuredError,
    data: Any | None = None,
    warnings: tuple[StructuredWarning, ...] = (),
) -> str:
    return Envelope(
        command=command, status="error", data=data, error=error, warnings=warnings
    ).to_json()


def partial_envelope(
    command: str,
    data: Any,
    error: StructuredError | None = None,
    warnings: tuple[StructuredWarning, ...] = (),
) -> str:
    return Envelope(
        command=command, status="partial", data=data, error=error, warnings=warnings
    ).to_json()
