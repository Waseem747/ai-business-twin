"""Application error types with stable API error codes."""
from __future__ import annotations


class TwinError(Exception):
    code = "twin_error"
    status_code = 400

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(TwinError):
    code = "not_found"
    status_code = 404


class PermissionDenied(TwinError):
    code = "permission_denied"
    status_code = 403


class ConflictError(TwinError):
    code = "conflict"
    status_code = 409


class ValidationError(TwinError):
    code = "validation_error"
    status_code = 422


class WorkflowError(TwinError):
    code = "workflow_error"
    status_code = 500


class ExcelConversionError(TwinError):
    code = "excel_conversion_error"
    status_code = 422
