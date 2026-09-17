"""Structured, model-readable errors for the ovf MCP tools.

A tool never returns a number it could not verify. When the library refuses an input, or the
adapter's own re-check fails, the call returns ``is_error=True`` with the same JSON body as its
text content and its structured content, which the calling model can act on::

    {"error": {"code": "...", "message": "...", "hint": "...", "tool": "...", "details": ...}}

``code`` is stable and machine-readable; ``message`` is the library's own text, unchanged.
Anything not anticipated here is left to the SDK, which reports a generic failure to the client
and logs the traceback to stderr.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_types import CallToolResult, TextContent
from pydantic import ValidationError

from ovf.ocf import OcfError, OcfIntegrityError, OcfSchemaError, OcfUnsupportedError
from ovf.waterfall import WaterfallConvergenceError

LIMITATIONS = "ovf://docs/limitations"


class DomainError(Exception):
    """An anticipated refusal, with a stable ``code`` and a hint for the caller."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details


def _validation_details(error: ValidationError) -> list[dict[str, str]]:
    return [
        {"loc": ".".join(str(part) for part in item["loc"]), "msg": item["msg"]}
        for item in error.errors()[:20]
    ]


def _raised_in_library(error: BaseException) -> bool:
    """True when the innermost frame that raised ``error`` belongs to the ``ovf`` library.

    The library signals a refusal with ``ValueError``. The same type raised by adapter code
    is a bug in the adapter, and must not reach the model disguised as a refusal.
    """
    traceback = error.__traceback__
    module = ""
    while traceback is not None:
        module = str(traceback.tb_frame.f_globals.get("__name__", ""))
        traceback = traceback.tb_next
    return module == "ovf" or module.startswith("ovf.")


def classify(error: BaseException) -> DomainError | None:
    """Map an anticipated exception to a ``DomainError``; ``None`` means a genuine crash."""
    if isinstance(error, DomainError):
        return error
    if isinstance(error, WaterfallConvergenceError):
        return DomainError(
            "convergence_failure",
            str(error),
            hint=(
                "The best-response search cycled or ran out of iterations, so no allocation is "
                "reported. Run conversion_equilibria to enumerate every conversion profile "
                "(up to 14 preferred positions); exit_waterfall also accepts max_iterations."
            ),
        )
    if isinstance(error, OcfIntegrityError):
        return DomainError(
            "ocf_integrity_error",
            str(error),
            hint="A file does not match its manifest checksum. Re-export the package, or pass "
            "verify_md5=false only if the mismatch is understood.",
        )
    if isinstance(error, OcfUnsupportedError):
        return DomainError(
            "ocf_unsupported",
            str(error),
            hint="Valid OCF that expresses a right ovf cannot represent without guessing. "
            "See ovf://docs/ocf.",
        )
    if isinstance(error, OcfSchemaError):
        return DomainError("ocf_schema_error", str(error), hint="Not OCF v1.2.0-shaped input.")
    if isinstance(error, OcfError):
        return DomainError("ocf_error", str(error))
    if isinstance(error, ValidationError):
        return DomainError(
            "invalid_terms",
            f"{error.error_count()} validation error(s) for {error.title}",
            hint="Correct the listed fields.",
            details=_validation_details(error),
        )
    if isinstance(error, RuntimeError) and _raised_in_library(error):
        return DomainError(
            "solver_failure",
            str(error),
            hint="A library solver could not produce a checked result; no numbers are "
            "returned. Report the input if it is within the documented scope.",
        )
    if isinstance(error, ValueError) and _raised_in_library(error):
        return DomainError(
            "refused_by_model",
            str(error),
            hint=(
                "The library refuses input outside its documented scope rather than guessing. "
                f"Check the message, then {LIMITATIONS}; do not retry with invented terms."
            ),
        )
    if isinstance(
        error, FileNotFoundError | NotADirectoryError | IsADirectoryError | FileExistsError
    ):
        return DomainError("file_error", str(error))
    if isinstance(error, PermissionError):
        return DomainError("file_error", str(error), hint="The server process cannot access it.")
    return None


def error_result(error: DomainError, tool: str) -> CallToolResult:
    """An ``is_error`` tool result whose text and structured content carry the same JSON."""
    body: dict[str, Any] = {"code": error.code, "message": error.message, "tool": tool}
    if error.hint:
        body["hint"] = error.hint
    if error.details is not None:
        body["details"] = error.details
    payload = json.loads(json.dumps({"error": body}, default=str))
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=True,
    )
