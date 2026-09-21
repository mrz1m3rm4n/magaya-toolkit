"""Domain read models for Magaya catalog/definition data.

Pure, in-memory representations of the reference data a Magaya install is
configured with: currencies, the chart of accounts, charge (item/service)
definitions, event definitions and working ports. They know nothing about SOAP
or XML — an infrastructure adapter turns the Magaya XML into these objects.

These catalogs give meaning to codes that other resources return as opaque
strings: an invoice's `Currency`, a charge's `Code`, a shipment event's name.

Read-only: these models are only ever populated from data the API returns.
Every field except the few Magaya always sends is optional, so a record that
omits a field never causes an error.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from magaya_toolkit.domain.common import Measure


class Currency(BaseModel):
    """An active currency as returned by `GetActiveCurrencies`.

    `code` comes from the `Code` attribute of `<Currency>` (e.g. "MXN"). The
    same element is embedded inside account and charge definitions, so this
    model is reused there.

    `exchange_rate` is a `Decimal`: Magaya sends rates at full precision
    (e.g. "0.05069297294009104254") and float would silently round them.
    """

    code: str | None = None
    name: str | None = None
    exchange_rate: Decimal | None = None
    decimal_places: int | None = None
    is_home_currency: bool | None = None


class EventDefinition(BaseModel):
    """A tracking-event definition as returned by `GetEventDefinitions`.

    These are the event names a Magaya install can stamp on a transaction
    (e.g. "Recolectado", "Delivered"). `include_in_tracking` marks the ones
    surfaced in customer-facing tracking.
    """

    name: str | None = None
    include_in_tracking: bool | None = None
    details: str | None = None


class AccountDefinition(BaseModel):
    """A chart-of-accounts entry as returned by `GetAccountDefinitions`.

    `parent_account` is recursive: Magaya nests the full parent account inside
    a child account, so the hierarchy is available without a second read.
    """

    type: str | None = None
    name: str | None = None
    number: str | None = None
    currency: Currency | None = None
    parent_account: AccountDefinition | None = None


class ChargeDefinition(BaseModel):
    """An item/service (charge) definition as returned by `GetChargeDefinitions`.

    `code` is the short charge code that appears on invoice lines; this catalog
    is what turns that opaque code into a description and an account.

    `account_definition` is the full nested `AccountDefinition` Magaya embeds
    (with its own currency and parent account), not just a reference.
    """

    type: str | None = None
    code: str | None = None
    description: str | None = None
    amount: Measure | None = None
    currency: Currency | None = None
    account_definition: AccountDefinition | None = None
    tax_definition_name: str | None = None
    iata_code: str | None = None
    notes: str | None = None
    enforce_3rd_party_billing: bool | None = None


class Port(BaseModel):
    """A working port as returned by `GetWorkingPorts`.

    `code` and `country_code` come from XML attributes (`Code` on `<Port>` and
    on `<Country>`).

    `methods` is a LIST: `<Method>` repeats, so one port can serve several
    transport modes (Air, Ocean, Ground, Mail) — or none at all.
    """

    code: str | None = None
    name: str | None = None
    country: str | None = None
    country_code: str | None = None
    methods: list[str] = []
    subdivision: str | None = None
    remarks: str | None = None
