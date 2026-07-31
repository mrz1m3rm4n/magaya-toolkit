"""Domain models for Magaya transactions.

These are the pure, in-memory representations of what we want to send to
Magaya. They know nothing about SOAP or XML — an infrastructure adapter is
responsible for turning them into the Magaya Transactions XML format.

Kept intentionally small for now; grow the fields as we map them against the
Magaya API reference (Methods / Transaction Flags / Transactions XML format).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class Party(BaseModel):
    """An entity involved in a transaction (shipper, consignee, client...)."""

    name: str
    magaya_guid: str | None = None


class ChargeLine(BaseModel):
    """A single charge/rate line on an invoice."""

    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    currency: str = "USD"

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_price


class Reference(BaseModel):
    """A shipment/booking reference to be created in Magaya."""

    number: str
    client: Party
    origin: str
    destination: str
    notes: str | None = None


class Invoice(BaseModel):
    """An invoice to be created in Magaya."""

    number: str
    bill_to: Party
    charges: list[ChargeLine] = Field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((c.total for c in self.charges), Decimal("0"))
