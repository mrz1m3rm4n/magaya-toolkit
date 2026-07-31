"""Ports: the boundaries the application talks to.

Defined as Protocols so the domain/application layers depend on abstractions,
not on concrete SOAP or lxml implementations. Adapters in `infrastructure/`
implement these.
"""

from __future__ import annotations

from typing import Protocol

from magaya_toolkit.domain.shipment import Shipment


class XmlValidator(Protocol):
    """Validates a Magaya XML document against an expected structure."""

    def validate(self, xml: bytes) -> None:
        """Raise `XmlValidationError` if `xml` is not valid; return None if OK."""
        ...


class ShipmentParser(Protocol):
    """Turns a Magaya `<Shipments>` XML document into domain shipments."""

    def parse(self, trans_list_xml: str | bytes) -> list[Shipment]:
        """Parse a `<Shipments>` document into `Shipment` objects.

        Raises `XmlValidationError` if the input is not a well-formed
        `<Shipments>` document. An empty or absent `<Shipments>` returns [].
        """
        ...


class MagayaReader(Protocol):
    """The read-only subset of the Magaya SOAP API the toolkit uses.

    Method names mirror the Magaya API reference so the mapping stays obvious.
    Wire-level 0/1 integer flags are exposed here as booleans; the adapter
    converts them at the transport boundary.
    """

    def start_session(self) -> int:
        """Open a session and return the numeric access key."""
        ...

    def end_session(self, access_key: int) -> None:
        """Close the session identified by `access_key`."""
        ...

    def get_first_trans_by_date(
        self,
        access_key: int,
        trans_type: str,
        start_date: str,
        end_date: str,
        record_quantity: int,
        backwards_order: bool = False,
        flags: int = 0,
    ) -> tuple[str, bool]:
        """Start a date-range query. Returns `(cookie, more_results)`.

        Dates use the `yyyy-MM-dd` format. This call does not return
        transaction XML; use `get_next_trans_by_date` with the cookie.
        """
        ...

    def get_next_trans_by_date(self, cookie: str) -> tuple[str, str, bool]:
        """Fetch the next batch. Returns `(trans_list_xml, next_cookie, more_results)`.

        The cookie is an in/out cursor: each call returns an *updated* cookie
        that encodes the advanced position and MUST be passed to the following
        call. Reusing the same cookie re-fetches the same page forever.
        """
        ...
