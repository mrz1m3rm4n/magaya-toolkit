"""Typed resource namespaces exposed by the `Magaya` SDK facade.

Each resource is bound to a `Magaya` facade and reuses its single open session.
Resources never touch the access key or pagination cookies directly — they read
the facade's `access_key` (which raises `SessionError` if the session is not
open) and delegate transport to the facade's client.

Read-only: resources only read and parse Magaya data; nothing here mutates it.
To add a new resource (invoices, rates, …), follow the same shape:
hold the facade, build the parser it needs, and expose typed read methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from magaya_toolkit.application.use_cases import collect_shipments
from magaya_toolkit.domain.entity import Entity, EntityContact, EntityType
from magaya_toolkit.domain.shipment import Shipment
from magaya_toolkit.infrastructure.xml.entity_parser import LxmlEntityParser
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

    def get(self, number: str, *, flags: int = 0) -> Shipment:
        """Fetch a single shipment by its number or GUID via `GetTransaction`.

        `number` is the shipment number, the Bill of Lading / Waybill number,
        or the transaction GUID — `GetTransaction` accepts any of them. Reuses
        the facade's OPEN session; accessing it before `Magaya.open()` raises
        `SessionError`. Raises `ApiError` if Magaya has no such transaction.
        """
        trans_xml = self._magaya.client.get_transaction(
            self._magaya.access_key, "SH", number, flags=flags
        )
        return self._parser.parse_one(trans_xml)


class EntitiesResource:
    """Read entities and their contacts through the facade's managed session."""

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._parser = LxmlEntityParser()

    def find(
        self,
        start_with: str = "",
        *,
        entity_type: EntityType | int | None = None,
        flags: int = 0,
    ) -> list[Entity]:
        """List entities, optionally filtered by name prefix and/or type.

        With no `entity_type`, reads all entities via `GetEntities`; with a type,
        reads via `GetEntitiesOfType`. Reuses the facade's OPEN session;
        accessing it before `Magaya.open()` raises `SessionError`.
        """
        client = self._magaya.client
        access_key = self._magaya.access_key
        if entity_type is None:
            entity_list_xml = client.get_entities(access_key, start_with, flags=flags)
        else:
            entity_list_xml = client.get_entities_of_type(
                access_key, start_with, int(entity_type), flags=flags
            )
        return self._parser.parse_entities(entity_list_xml)

    def contacts(self, entity_guid: str, *, flags: int = 0) -> list[EntityContact]:
        """List the contacts of one entity by its GUID.

        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`.
        """
        contact_list_xml = self._magaya.client.get_entity_contacts(
            self._magaya.access_key, entity_guid, flags=flags
        )
        return self._parser.parse_contacts(contact_list_xml)
