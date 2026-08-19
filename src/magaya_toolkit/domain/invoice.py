"""Domain read model for Magaya invoices.

Pure, in-memory representation of an invoice as read back from the Magaya API.
It knows nothing about SOAP or XML — an infrastructure adapter is responsible
for turning the Magaya invoice XML into these objects.

Read-only: this model is only ever populated from data the API returns; the
toolkit never writes invoices. Every field except `number` is optional so that
fields absent in a given invoice's XML never cause an error.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

__all__ = ["Invoice"]


class Invoice(BaseModel):
    """An invoice as returned by the Magaya API.

    Only `number` is required; everything else defaults to None to tolerate
    invoices that omit a field. `entity_name` is the bill-to client name and
    `issued_by_name` is the issuing party — both read from a nested `<Name>`.
    """

    guid: str | None = None
    number: str
    type_code: str | None = None
    status: str | None = None

    created_on: datetime | None = None
    due_date: datetime | None = None

    entity_name: str | None = None
    issued_by_name: str | None = None

    total_amount: Decimal | None = None
    home_currency: str | None = None
    currency: str | None = None
    total_amount_in_currency: Decimal | None = None
    exchange_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    tax_amount_in_currency: Decimal | None = None

    is_prepaid: bool | None = None
    is_periodic: bool | None = None
    is_printed: bool | None = None
    is_fiscal_printed: bool | None = None
    has_attachments: bool | None = None
