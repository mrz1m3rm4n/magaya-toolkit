"""Domain errors. Pure — no framework or transport dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field


class MagayaError(Exception):
    """Base class for every error raised by the toolkit."""


@dataclass
class XmlValidationError(MagayaError):
    """Raised when an XML document does not match the expected structure.

    `problems` holds one human-readable message per issue found so the caller
    can report all of them at once instead of failing on the first.
    """

    message: str
    problems: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - trivial
        if not self.problems:
            return self.message
        joined = "\n  - ".join(self.problems)
        return f"{self.message}\n  - {joined}"


class ApiError(MagayaError):
    """Raised when the Magaya API returns an error code or a SOAP fault."""


class SessionError(MagayaError):
    """Raised when a resource is used before the Magaya session is open."""
