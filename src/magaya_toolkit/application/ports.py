"""Ports: the boundaries the application talks to.

Defined as Protocols so the domain/application layers depend on abstractions,
not on concrete SOAP or lxml implementations. Adapters in `infrastructure/`
implement these.
"""

from __future__ import annotations

from typing import Protocol


class XmlValidator(Protocol):
    """Validates a Magaya XML document against an expected structure."""

    def validate(self, xml: bytes) -> None:
        """Raise `XmlValidationError` if `xml` is not valid; return None if OK."""
        ...


class MagayaApi(Protocol):
    """The subset of the Magaya SOAP API the toolkit uses.

    Method names mirror the Magaya API reference so the mapping stays obvious.
    """

    def start_session(self) -> str: ...

    def end_session(self) -> None: ...

    def set_transaction(self, xml: bytes) -> str:
        """Submit a transaction (SetTransaction). Returns the Magaya response."""
        ...
