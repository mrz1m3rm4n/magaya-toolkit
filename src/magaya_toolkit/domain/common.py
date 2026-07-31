"""Shared domain read models used across Magaya resources.

Pure, in-memory value objects reused by more than one resource (shipments,
entities, …). They know nothing about SOAP or XML — infrastructure adapters
turn Magaya XML into these objects.

Read-only: these models are only ever populated from data the API returns.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class Measure(BaseModel):
    """A numeric quantity with an optional unit or currency.

    Used for weight/volume (text value + `Unit` attribute) and monetary value
    (text value + `Currency` attribute).
    """

    value: Decimal
    unit: str | None = None


class Address(BaseModel):
    """A postal/contact address as returned by the Magaya API.

    A single address may carry several `<Street>` lines, so `street` is a list.
    Every field is optional so an address that omits parts never causes an error.
    """

    street: list[str] = []
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country: str | None = None
    country_code: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
