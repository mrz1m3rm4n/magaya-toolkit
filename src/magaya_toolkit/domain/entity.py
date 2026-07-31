"""Domain read models for Magaya entities and their contacts.

Pure, in-memory representations of an entity (Client, Carrier, Vendor, …) and an
entity contact as read back from the Magaya API. They know nothing about SOAP or
XML — an infrastructure adapter turns the Magaya XML into these objects.

Read-only: these models are only ever populated from data the API returns; the
toolkit never writes entities. Only `Entity.kind` is required (derived from the
XML element tag); every other field is optional so that fields absent in a given
entity's XML never cause an error.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel

from magaya_toolkit.domain.common import Address, Measure


class Entity(BaseModel):
    """An entity (Client, Carrier, Vendor, …) as returned by the Magaya API.

    `kind` is derived from the XML element local-name (`Client`, `Carrier`,
    `Vendor`, `ForwardingAgent`, `Employee`, `Division`, …). Only `kind` is
    required; everything else defaults to None to tolerate entities that omit a
    field.
    """

    guid: str | None = None
    kind: str

    name: str | None = None
    entity_id: str | None = None
    account_number: str | None = None
    type: str | None = None

    email: str | None = None
    phone: str | None = None

    contact_first_name: str | None = None
    contact_last_name: str | None = None

    exporter_id: str | None = None
    exporter_id_type: str | None = None

    created_on: datetime | None = None

    is_prepaid: bool | None = None
    is_inactive: bool | None = None

    balance: Measure | None = None

    address: Address | None = None
    billing_address: Address | None = None


class EntityContact(BaseModel):
    """A contact belonging to an entity, as returned by the Magaya API.

    The name/phone/email fields are read from the contact's own `<Address>`.
    Every field is optional to tolerate contacts that omit parts.
    """

    guid: str | None = None
    name: str | None = None
    type: str | None = None
    created_on: datetime | None = None

    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class EntityType(IntEnum):
    """Entity type codes accepted by `GetEntitiesOfType` (bitmask values).

    `CUSTOMER` returns `<Client>` elements. `ANY` (0) means no type filter.
    """

    ANY = 0x000
    CUSTOMER = 0x002
    WAREHOUSE_PROVIDER = 0x004
    FORWARDING_AGENT = 0x008
    CARRIER = 0x020
    VENDOR = 0x040
    EMPLOYEE = 0x080
    SALESMAN = 0x100
    DIVISION = 0x200
