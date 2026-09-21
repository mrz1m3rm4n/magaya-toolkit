"""Domain read models for Magaya freight rates.

A rate answers "what does this service cost on this lane": it pairs a charge
definition with a price, scoped by origin/destination, transport mode and (for
client and carrier rates) a party.

The three rate reads (`GetStandardRates`, `GetClientRates`, `GetCarrierRates`)
all return the same `<Rate>` shape under a different document root, so one
`Rate` model covers all three; `Rate.type` says which kind it is.

Read-only: these models are only ever populated from data the API returns.
Every field is optional — rates are sparsely filled and vary by `apply_by`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from magaya_toolkit.domain.catalog import ChargeDefinition, Currency
from magaya_toolkit.domain.common import Measure


class PartyRef(BaseModel):
    """A light pointer to the entity a rate belongs to (the carrier, …).

    Magaya inlines the party's ENTIRE entity record inside every rate — address,
    balance, payment terms, custom fields and all. Keeping only the pointer here
    stops every rate from carrying a duplicate copy of master data; read the
    full record with `Magaya.entities` when you actually need it.
    """

    guid: str | None = None
    name: str | None = None
    type: str | None = None


class ModeOfTransportation(BaseModel):
    """One configured mode of transportation a rate applies to."""

    code: str | None = None
    description: str | None = None
    method: str | None = None


class ApplicableModes(BaseModel):
    """Which transport modes a rate applies to.

    `all_methods_included` is Magaya's "applies to everything" switch; when it
    is false, `methods` (Air/Ocean/Ground/Mail) and the install's configured
    `modes` say which.
    """

    all_methods_included: bool | None = None
    methods: list[str] = []
    modes: list[ModeOfTransportation] = []


class Package(BaseModel):
    """A package/container type a package-based rate is priced against."""

    type: str | None = None
    code: str | None = None
    name: str | None = None
    container_code: str | None = None
    container_equip_type: str | None = None
    methods: list[str] = []


class PackageRate(BaseModel):
    """One priced line of a package-based rate: a package type and its price."""

    package: Package | None = None
    price: Measure | None = None


class Rate(BaseModel):
    """A freight rate as returned by the three rate reads.

    `apply_by` selects how the price is calculated — Magaya supports `Package`,
    `Weight`, `Volume`, `Pieces`, `Formula` and `Unknown`, and each keeps its
    prices in its own element.

    Only `Package` pricing is parsed today, into `package_rates`; it is the only
    variant that could be confirmed against a live install. For a rate whose
    `apply_by` is something else, the descriptive fields are still populated and
    `package_rates` is empty — check `apply_by` before reading prices.
    """

    guid: str | None = None
    type: str | None = None

    charge_definition: ChargeDefinition | None = None
    carrier: PartyRef | None = None

    services: list[str] = []
    origin_country: str | None = None
    origin_country_code: str | None = None
    destination_country: str | None = None
    destination_country_code: str | None = None
    applicable_modes: ApplicableModes | None = None

    currency: Currency | None = None
    apply_by: str | None = None
    package_rates: list[PackageRate] = []

    frequency: str | None = None
    created_on: datetime | None = None
    use_gross_weight: bool | None = None
    is_hazardous: bool | None = None
    is_automatic_create_charge: bool | None = None

    @property
    def prices(self) -> list[Decimal]:
        """Every price this rate carries, for a quick min/max without nesting."""
        return [pr.price.value for pr in self.package_rates if pr.price is not None]
