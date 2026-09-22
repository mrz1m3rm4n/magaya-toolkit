"""Magaya toolkit: a read-only, typed Python SDK for the Magaya API.

The primary interface is the `Magaya` facade:

    from magaya_toolkit import Magaya, MagayaSettings

    with Magaya(MagayaSettings()) as magaya:
        shipments = magaya.shipments.list("2025-01-01", "2025-01-31")
"""

from magaya_toolkit.domain.attachment import (
    ATTACH_DOCS_SUMMARY,
    Attachment,
    AttachmentRef,
    DocumentRef,
    WebDocument,
)
from magaya_toolkit.domain.catalog import (
    AccountDefinition,
    ChargeDefinition,
    Currency,
    EventDefinition,
    Port,
)
from magaya_toolkit.domain.common import Address, Measure, Package
from magaya_toolkit.domain.entity import Entity, EntityContact, EntityType
from magaya_toolkit.domain.errors import (
    ApiError,
    MagayaError,
    SessionError,
    XmlValidationError,
)
from magaya_toolkit.domain.inventory import (
    InventoryItem,
    ItemDefinition,
    WarehouseLocation,
)
from magaya_toolkit.domain.invoice import Invoice
from magaya_toolkit.domain.rate import (
    ApplicableModes,
    ModeOfTransportation,
    PackageRate,
    PartyRef,
    Rate,
)
from magaya_toolkit.domain.shipment import Shipment
from magaya_toolkit.domain.transaction import TransactionRef
from magaya_toolkit.facade import Magaya
from magaya_toolkit.infrastructure.config import MagayaSettings

__version__ = "0.1.0"

__all__ = [
    "ATTACH_DOCS_SUMMARY",
    "AccountDefinition",
    "Address",
    "ApiError",
    "ApplicableModes",
    "Attachment",
    "AttachmentRef",
    "ChargeDefinition",
    "Currency",
    "DocumentRef",
    "Entity",
    "EntityContact",
    "EntityType",
    "EventDefinition",
    "InventoryItem",
    "Invoice",
    "ItemDefinition",
    "Magaya",
    "MagayaError",
    "MagayaSettings",
    "Measure",
    "ModeOfTransportation",
    "Package",
    "PackageRate",
    "PartyRef",
    "Port",
    "Rate",
    "SessionError",
    "Shipment",
    "TransactionRef",
    "WarehouseLocation",
    "WebDocument",
    "XmlValidationError",
]
