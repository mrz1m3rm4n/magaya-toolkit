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
from magaya_toolkit.domain.catalog import (
    AccountDefinition,
    ChargeDefinition,
    Currency,
    EventDefinition,
    Port,
)
from magaya_toolkit.domain.entity import Entity, EntityContact, EntityType
from magaya_toolkit.domain.invoice import Invoice
from magaya_toolkit.domain.rate import Rate
from magaya_toolkit.domain.shipment import Shipment
from magaya_toolkit.domain.transaction import TransactionRef
from magaya_toolkit.infrastructure.xml.catalog_parser import LxmlCatalogParser
from magaya_toolkit.infrastructure.xml.entity_parser import LxmlEntityParser
from magaya_toolkit.infrastructure.xml.invoice_parser import LxmlInvoiceParser
from magaya_toolkit.infrastructure.xml.rate_parser import LxmlRateParser
from magaya_toolkit.infrastructure.xml.shipment_parser import LxmlShipmentParser
from magaya_toolkit.infrastructure.xml.transaction_parser import LxmlGuidItemsParser

if TYPE_CHECKING:
    from magaya_toolkit.facade import Magaya


class ShipmentsResource:
    """Read shipments through the facade's managed session."""

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._parser = LxmlShipmentParser()
        self._log_parser = LxmlGuidItemsParser()

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

    def accounting_transactions(
        self, number: str, *, flags: int = 0
    ) -> list[TransactionRef]:
        """List the invoices/bills billed for this shipment (by shipment number).

        Returns lightweight `TransactionRef` pointers to the accounting
        transactions related to the shipment; fetch each full invoice with
        `Magaya.invoices.get(...)`. Reuses the facade's OPEN session; accessing
        it before `Magaya.open()` raises `SessionError`.
        """
        trans_xml = self._magaya.client.get_accounting_transactions(
            self._magaya.access_key, "SH", number, flags=flags
        )
        return self._log_parser.parse(trans_xml)

    def exists(self, number: str) -> bool:
        """Return whether a shipment with this number/GUID exists (cheap check).

        A lightweight existence probe (`ExistsTransaction`) that does not fetch
        the shipment. Reuses the facade's OPEN session; accessing it before
        `Magaya.open()` raises `SessionError`.
        """
        return self._magaya.client.exists_transaction(
            self._magaya.access_key, "SH", number
        )

    def status(self, number: str) -> str:
        """Return this shipment's status without fetching the full record.

        A lightweight probe (`GetTransactionStatus`, e.g. "Delivered"). Reuses
        the facade's OPEN session; accessing it before `Magaya.open()` raises
        `SessionError`. Raises `ApiError` if no such shipment exists.
        """
        return self._magaya.client.get_transaction_status(
            self._magaya.access_key, "SH", number
        )


class EntitiesResource:
    """Read entities and their contacts through the facade's managed session."""

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._parser = LxmlEntityParser()
        self._log_parser = LxmlGuidItemsParser()

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

    def transactions(
        self, entity_guid: str, start_date: str, end_date: str, *, flags: int = 0
    ) -> list[TransactionRef]:
        """List this entity's accounting-transaction references in a date range.

        Returns lightweight `TransactionRef` pointers to the entity's accounting
        transactions (invoices, bills, …); fetch each full invoice with
        `Magaya.invoices.get(...)`. Dates use the `yyyy-MM-dd` format. Reuses the
        facade's OPEN session; accessing it before `Magaya.open()` raises
        `SessionError`.
        """
        acctrans_list_xml = self._magaya.client.get_entity_transactions(
            self._magaya.access_key, entity_guid, start_date, end_date, flags=flags
        )
        return self._log_parser.parse(acctrans_list_xml)


class InvoicesResource:
    """Read invoices through the facade's managed session."""

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._log_parser = LxmlGuidItemsParser()
        self._invoice_parser = LxmlInvoiceParser()

    def query(
        self,
        start_date: str,
        end_date: str,
        *,
        log_entry_type: int = 1,
        flags: int = 0,
    ) -> list[TransactionRef]:
        """List invoice references logged in a date range via `QueryLog`.

        Returns lightweight `TransactionRef` pointers; fetch the full invoice for
        each with `get`. Dates use the `yyyy-MM-ddTHH:mm:ss` format; keep the
        window narrow (wide ranges time out). `log_entry_type` is a bitmask of
        log operations to include and defaults to 1 (Creation).

        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`.
        """
        trans_list_xml = self._magaya.client.query_log(
            self._magaya.access_key,
            start_date,
            end_date,
            log_entry_type,
            "IN",
            flags,
        )
        return self._log_parser.parse(trans_list_xml)

    def get(self, number: str, *, flags: int = 0) -> Invoice:
        """Fetch a single invoice by its number or GUID via `GetTransaction`.

        `number` is the invoice number or the transaction GUID —
        `GetTransaction` accepts either. Reuses the facade's OPEN session;
        accessing it before `Magaya.open()` raises `SessionError`. Raises
        `ApiError` if Magaya has no such transaction.
        """
        trans_xml = self._magaya.client.get_transaction(
            self._magaya.access_key, "IN", number, flags=flags
        )
        return self._invoice_parser.parse_one(trans_xml)

    def related(self, number: str, *, flags: int = 0) -> list[TransactionRef]:
        """List the transaction(s) related to this invoice (e.g. the shipment it bills).

        Returns lightweight `TransactionRef` pointers to the related operations
        transaction(s); fetch each full shipment with `Magaya.shipments.get(...)`.
        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`.
        """
        trans_xml = self._magaya.client.get_related_transactions(
            self._magaya.access_key, "IN", number, flags=flags
        )
        return self._log_parser.parse(trans_xml)

    def exists(self, number: str) -> bool:
        """Return whether an invoice with this number/GUID exists (cheap check).

        A lightweight existence probe (`ExistsTransaction`) that does not fetch
        the invoice. Reuses the facade's OPEN session; accessing it before
        `Magaya.open()` raises `SessionError`.
        """
        return self._magaya.client.exists_transaction(
            self._magaya.access_key, "IN", number
        )

    def status(self, number: str) -> str:
        """Return this invoice's status without fetching the full record.

        A lightweight probe (`GetTransactionStatus`, e.g. "Open", "Paid").
        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`. Raises `ApiError` if no such invoice exists.
        """
        return self._magaya.client.get_transaction_status(
            self._magaya.access_key, "IN", number
        )


class CatalogResource:
    """Read the install's reference data through the facade's managed session.

    Catalogs are what give meaning to the codes other resources return: an
    invoice's currency code, a charge line's code, a shipment's event name, a
    port code. Every read here is a single call with no pagination.
    """

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._parser = LxmlCatalogParser()

    def currencies(self) -> list[Currency]:
        """List the active currencies.

        Exchange rates come back as `Decimal` at Magaya's full precision.
        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`.
        """
        currency_list_xml = self._magaya.client.get_active_currencies(
            self._magaya.access_key
        )
        return self._parser.parse_currencies(currency_list_xml)

    def events(self) -> list[EventDefinition]:
        """List the tracking-event definitions this install can stamp.

        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`.
        """
        event_definition_list_xml = self._magaya.client.get_event_definitions(
            self._magaya.access_key
        )
        return self._parser.parse_event_definitions(event_definition_list_xml)

    def accounts(self) -> list[AccountDefinition]:
        """List the chart of accounts.

        Each account carries its currency and, when it has one, its full parent
        account nested recursively. Reuses the facade's OPEN session; accessing
        it before `Magaya.open()` raises `SessionError`.
        """
        account_list_xml = self._magaya.client.get_account_definitions(
            self._magaya.access_key
        )
        return self._parser.parse_account_definitions(account_list_xml)

    def charges(self) -> list[ChargeDefinition]:
        """List the item/service (charge) definitions.

        This is the catalog that turns an invoice line's opaque charge code into
        a description and an account. The response is large on a mature install
        (a few MB); read it once and keep it. Reuses the facade's OPEN session;
        accessing it before `Magaya.open()` raises `SessionError`.
        """
        service_list_xml = self._magaya.client.get_charge_definitions(
            self._magaya.access_key
        )
        return self._parser.parse_charge_definitions(service_list_xml)

    def client_charges(self, client_guid: str) -> list[ChargeDefinition]:
        """List one client's custom charge definitions, overriding the globals.

        `client_guid` must be a Client entity's GUID; another entity type is
        rejected with `unknown_object`. A client with no custom charges returns
        an empty list, not an error. Reuses the facade's OPEN session; accessing
        it before `Magaya.open()` raises `SessionError`.
        """
        charge_list_xml = self._magaya.client.get_client_charge_definitions(
            self._magaya.access_key, client_guid
        )
        return self._parser.parse_custom_charge_definitions(charge_list_xml)

    def ports(self) -> list[Port]:
        """List the working ports defined in Magaya.

        A port may serve several transport modes, so `Port.methods` is a list
        (Air/Ocean/Ground/Mail) and may be empty.

        Unlike every other read here, `GetWorkingPorts` takes no session key, so
        this call works without an open session.
        """
        ports_list_xml = self._magaya.client.get_working_ports()
        return self._parser.parse_ports(ports_list_xml)


class RatesResource:
    """Read freight rates through the facade's managed session.

    All three reads share a lane filter — origin port, destination port and
    transport mode. Ports use Magaya's CountryCode+PortCode form ("MXZLO" is
    Manzanillo, Mexico; pair `Port.country_code` with `Port.code` from
    `Magaya.catalog.ports()` to build one). `method` is "Air", "Ocean" or
    "Ground". Leave any of them out to not filter on it; leave all out to read
    the whole list.

    A port code that is not a working port raises `ApiError`
    (`invalid_operation`) rather than returning nothing.
    """

    def __init__(self, magaya: Magaya) -> None:
        self._magaya = magaya
        self._parser = LxmlRateParser()

    def standard(
        self, *, org_port: str = "", dest_port: str = "", method: str = ""
    ) -> list[Rate]:
        """List the standard (house) rates.

        Reuses the facade's OPEN session; accessing it before `Magaya.open()`
        raises `SessionError`.
        """
        rate_list_xml = self._magaya.client.get_standard_rates(
            self._magaya.access_key, org_port, dest_port, method
        )
        return self._parser.parse(rate_list_xml)

    def for_client(
        self,
        client_guid: str,
        *,
        org_port: str = "",
        dest_port: str = "",
        method: str = "",
        include_standard: bool = False,
    ) -> list[Rate]:
        """List one client's negotiated rates.

        Set `include_standard` to also get the standard rates that apply to this
        client. `client_guid` must be a Client entity's GUID; another entity
        type raises `ApiError` (`unknown_object`). Reuses the facade's OPEN
        session; accessing it before `Magaya.open()` raises `SessionError`.
        """
        rate_list_xml = self._magaya.client.get_client_rates(
            self._magaya.access_key,
            client_guid,
            org_port,
            dest_port,
            method,
            include_standard,
        )
        return self._parser.parse(rate_list_xml)

    def for_carrier(
        self,
        carrier_guid: str,
        *,
        org_port: str = "",
        dest_port: str = "",
        method: str = "",
    ) -> list[Rate]:
        """List one carrier's rates.

        `carrier_guid` must be a Carrier entity's GUID; another entity type
        raises `ApiError` (`unknown_object`). Reuses the facade's OPEN session;
        accessing it before `Magaya.open()` raises `SessionError`.
        """
        rate_list_xml = self._magaya.client.get_carrier_rates(
            self._magaya.access_key, carrier_guid, org_port, dest_port, method
        )
        return self._parser.parse(rate_list_xml)
