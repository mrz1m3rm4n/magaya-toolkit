"""Application use cases.

Thin orchestration over the ports. These functions depend only on the
`application` ports and `domain` models — never on httpx, lxml, or SOAP — so
they stay testable with fakes and free of transport concerns.

Read-only: the only use case so far lists shipments for a date range.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol

from magaya_toolkit.application.ports import ShipmentParser
from magaya_toolkit.domain.shipment import Shipment


def collect_shipments(
    chunks: Iterable[str],
    parser: ShipmentParser,
    max_results: int | None = None,
) -> list[Shipment]:
    """Parse `<Shipments>` chunks into deduplicated, optionally capped shipments.

    Parses each `trans_list_xml` chunk and aggregates the results. Magaya pages
    can repeat the same shipment across chunks, so results are deduplicated by
    `guid` (first occurrence wins); shipments without a `guid` are always kept.
    If `max_results` is given, iteration stops as soon as that many shipments
    have been collected.

    Pure and transport-agnostic: it consumes an iterable of XML chunks, so both
    the session-managed reader and the SDK facade can reuse it.
    """
    collected: list[Shipment] = []
    seen_guids: set[str] = set()

    for chunk in chunks:
        for shipment in parser.parse(chunk):
            if shipment.guid is not None:
                if shipment.guid in seen_guids:
                    continue
                seen_guids.add(shipment.guid)
            collected.append(shipment)
            if max_results is not None and len(collected) >= max_results:
                return collected

    return collected


class TransactionReader(Protocol):
    """The read capability `list_shipments` needs from a Magaya reader.

    Kept minimal on purpose: the concrete `MagayaSoapClient` satisfies it via
    its `read_transactions_by_date` iterator.
    """

    def read_transactions_by_date(
        self,
        trans_type: str,
        start_date: str,
        end_date: str,
        record_quantity: int = 5,
        backwards_order: bool = False,
        flags: int = 0,
    ) -> Iterator[str]:
        """Yield each `trans_list_xml` batch for a date range."""
        ...


def list_shipments(
    reader: TransactionReader,
    parser: ShipmentParser,
    start_date: str,
    end_date: str,
    trans_type: str = "SH",
    record_quantity: int = 5,
    backwards_order: bool = False,
    max_results: int | None = None,
) -> list[Shipment]:
    """List shipments in a date range, deduplicated and optionally capped.

    Reads each `trans_list_xml` batch, parses it into shipments, and aggregates
    them. Magaya pages can repeat the same shipment across batches, so results
    are deduplicated by `guid` (first occurrence wins); shipments without a
    `guid` are always kept. If `max_results` is given, iteration stops as soon
    as that many shipments have been collected.

    Dates use the `yyyy-MM-dd` format.
    """
    chunks = reader.read_transactions_by_date(
        trans_type=trans_type,
        start_date=start_date,
        end_date=end_date,
        record_quantity=record_quantity,
        backwards_order=backwards_order,
    )
    return collect_shipments(chunks, parser, max_results)
