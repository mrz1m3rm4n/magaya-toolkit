"""Magaya toolkit: a read-only, typed Python SDK for the Magaya API.

The primary interface is the `Magaya` facade:

    from magaya_toolkit import Magaya, MagayaSettings

    with Magaya(MagayaSettings()) as magaya:
        shipments = magaya.shipments.list("2025-01-01", "2025-01-31")
"""

from magaya_toolkit.domain.errors import (
    ApiError,
    MagayaError,
    SessionError,
    XmlValidationError,
)
from magaya_toolkit.domain.shipment import Measure, Shipment
from magaya_toolkit.facade import Magaya
from magaya_toolkit.infrastructure.config import MagayaSettings

__version__ = "0.1.0"

__all__ = [
    "ApiError",
    "Magaya",
    "MagayaError",
    "MagayaSettings",
    "Measure",
    "SessionError",
    "Shipment",
    "XmlValidationError",
]
