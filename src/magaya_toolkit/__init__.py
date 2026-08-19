"""Magaya toolkit: a read-only, typed Python SDK for the Magaya API.

The primary interface is the `Magaya` facade:

    from magaya_toolkit import Magaya, MagayaSettings

    with Magaya(MagayaSettings()) as magaya:
        shipments = magaya.shipments.list("2025-01-01", "2025-01-31")
"""

from magaya_toolkit.domain.common import Address, Measure
from magaya_toolkit.domain.entity import Entity, EntityContact, EntityType
from magaya_toolkit.domain.errors import (
    ApiError,
    MagayaError,
    SessionError,
    XmlValidationError,
)
from magaya_toolkit.domain.invoice import Invoice
from magaya_toolkit.domain.shipment import Shipment
from magaya_toolkit.domain.transaction import TransactionRef
from magaya_toolkit.facade import Magaya
from magaya_toolkit.infrastructure.config import MagayaSettings

__version__ = "0.1.0"

__all__ = [
    "Address",
    "ApiError",
    "Entity",
    "EntityContact",
    "EntityType",
    "Invoice",
    "Magaya",
    "MagayaError",
    "MagayaSettings",
    "Measure",
    "SessionError",
    "Shipment",
    "TransactionRef",
    "XmlValidationError",
]
