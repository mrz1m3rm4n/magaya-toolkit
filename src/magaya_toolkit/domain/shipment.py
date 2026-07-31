"""Domain read model for Magaya shipments.

Pure, in-memory representation of a shipment as read back from the Magaya API.
It knows nothing about SOAP or XML — an infrastructure adapter is responsible
for turning the Magaya Shipments XML into these objects.

Read-only: this model is only ever populated from data the API returns; the
toolkit never writes shipments. Every field except `number` and `mode` is
optional so that fields absent in a given shipment's XML never cause an error.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Measure(BaseModel):
    """A numeric quantity with an optional unit or currency.

    Used for weight/volume (text value + `Unit` attribute) and monetary value
    (text value + `Currency` attribute).
    """

    value: Decimal
    unit: str | None = None


class Shipment(BaseModel):
    """A shipment (Ocean or Air) as returned by the Magaya API.

    `mode` is derived from the XML element local-name (`OceanShipment` -> "Ocean",
    `AirShipment` -> "Air"). Only `number` and `mode` are required; everything
    else defaults to None to tolerate shipments that omit a field.
    """

    guid: str | None = None
    number: str
    mode: str
    type_code: str | None = None

    direction: str | None = None
    status: str | None = None
    service: str | None = None
    layout_type: str | None = None

    created_on: datetime | None = None
    created_by: str | None = None

    shipper_name: str | None = None
    consignee_name: str | None = None
    carrier_name: str | None = None
    destination_agent_name: str | None = None

    origin_port: str | None = None
    destination_port: str | None = None
    delivery_port: str | None = None

    description_of_goods: str | None = None

    total_pieces: int | None = None
    total_weight: Measure | None = None
    total_volume: Measure | None = None
    total_value: Measure | None = None

    estimated_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    estimated_departure: datetime | None = None
    actual_departure: datetime | None = None

    booking_number: str | None = None
    master_number: str | None = None
    master_guid: str | None = None

    mode_of_transport_code: str | None = None
    has_attachments: bool | None = None
