class VariaQError(Exception):
    """Base exception for actionable VariaQ errors."""


class ValidationError(VariaQError):
    """A problem, solution, or configuration is invalid."""


class MissingOptionalDependency(VariaQError):
    """A requested solver needs an optional dependency."""


class BackendUnavailableError(VariaQError):
    """A requested local backend is not available on this host."""

    def __init__(self, message: str, *, backend_name: str, provider: str) -> None:
        super().__init__(message)
        self.backend_name = backend_name
        self.provider = provider


class UnsafeBackendError(VariaQError):
    """A backend violates VariaQ's explicit execution safety policy."""


class DuplicateRunError(VariaQError):
    """A run ID already exists and cannot be overwritten."""


class SolverLimitError(VariaQError):
    """An instance exceeds a solver's explicit safety bound."""
