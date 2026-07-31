"""Typed resource namespaces exposed by the `Magaya` SDK facade.

Each resource is bound to a `Magaya` facade and reuses its single open session.
Resources never touch the access key or pagination cookies directly — they read
the facade's `access_key` (which raises `SessionError` if the session is not
open) and delegate transport to the facade's client.

Read-only: resources only read and parse Magaya data; nothing here mutates it.
To add a new resource (invoices, entities, …), follow the same shape:
hold the facade, build the parser it needs, and expose typed read methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from magaya_toolkit.application.use_cases import collect_shipments
from magaya_toolkit.domain.shipment import Shipment
from magaya_toolkit.infrastructure.xml.shipment_parser import LxmlShipmentParser

if TYPE_CHECKING:
    from magaya_toolkit.facade import Magaya


class ShipmentsResource:
    """Read shipments through the facade's managed session."""

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._parser = LxmlShipmentParser()

    def list(
        self,
        start_date: str,
        end_date: str,
        *,
        trans_type: str = "SH",
        record_quantity: int = 5,
        backwards: bool = False,
        max_results: int | None = None,
    ) -> list[Shipment]:
        """List shipments in a date range, deduplicated and optionally capped.

        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        (e.g. calling this outside a `with` block) raises `SessionError`.
        Dates use the `yyyy-MM-dd` format.
        """
        chunks = self._magaya.client.iter_transactions_by_date(
            self._magaya.access_key,
            trans_type,
            start_date,
            end_date,
            record_quantity,
            backwards,
        )
        return collect_shipments(chunks, self._parser, max_results)
