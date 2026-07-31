"""Unit tests for LxmlShipmentParser. No network access.

Canned <Shipments> documents exercise the namespace-aware, direct-children-only
parsing rules that matter against the real Magaya XML.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.shipment_parser import LxmlShipmentParser

_NS = "http://www.magaya.com/XMLSchema/V1"

# One Ocean + one Air shipment. The Ocean shipment hides a NESTED <Number>
# deep inside <Items> to prove the parser only reads the top-level field. The
# Air shipment omits ActualArrivalDate on purpose.
_TWO_SHIPMENTS = f"""<?xml version="1.0" encoding="utf-8"?>
<Shipments xmlns="{_NS}">
  <OceanShipment GUID="ocean-guid-1" Type="SH">
    <Number>OCEAN-001</Number>
    <Direction>Export</Direction>
    <Status>In Transit</Status>
    <CreatedOn>2025-01-15T09:30:00</CreatedOn>
    <ShipperName>Acme Corp</ShipperName>
    <ConsigneeName>Globex</ConsigneeName>
    <OriginPort Code="USMIA">Miami</OriginPort>
    <DestinationPort Code="ESVLC">Valencia</DestinationPort>
    <TotalWeight Unit="kg">1234.50</TotalWeight>
    <EstimatedArrivalDate>2025-02-01T12:00:00</EstimatedArrivalDate>
    <ActualArrivalDate>2025-02-02T08:15:00</ActualArrivalDate>
    <HasAttachments>true</HasAttachments>
    <Items>
      <Item>
        <Number>SHOULD-NOT-WIN</Number>
      </Item>
    </Items>
  </OceanShipment>
  <AirShipment GUID="air-guid-2" Type="SH">
    <Number>AIR-002</Number>
    <Direction>Import</Direction>
    <Status>Delivered</Status>
    <ShipperName>Initech</ShipperName>
    <ConsigneeName>Umbrella</ConsigneeName>
    <OriginPort Code="DEFRA">Frankfurt</OriginPort>
    <DestinationPort Code="USJFK">New York</DestinationPort>
    <TotalWeight Unit="kg">42.0</TotalWeight>
    <EstimatedArrivalDate>2025-03-10T18:00:00</EstimatedArrivalDate>
    <HasAttachments>false</HasAttachments>
  </AirShipment>
</Shipments>"""


def test_parses_ocean_and_air_reading_only_top_level_fields():
    shipments = LxmlShipmentParser().parse(_TWO_SHIPMENTS)
    assert len(shipments) == 2

    ocean, air = shipments

    # Mode derived from the element local-name.
    assert ocean.mode == "Ocean"
    assert air.mode == "Air"

    # Element attributes.
    assert ocean.guid == "ocean-guid-1"
    assert ocean.type_code == "SH"

    # CRITICAL: the nested <Number> inside <Items> must NOT win.
    assert ocean.number == "OCEAN-001"

    # Ports read from Code attributes.
    assert ocean.origin_port == "USMIA"
    assert ocean.destination_port == "ESVLC"

    # Measure: text value + Unit attribute.
    assert ocean.total_weight is not None
    assert ocean.total_weight.value == Decimal("1234.50")
    assert ocean.total_weight.unit == "kg"

    assert ocean.direction == "Export"
    assert ocean.has_attachments is True
    assert air.has_attachments is False

    # Dates parsed to datetime (naive, matching the tz-less Magaya XML).
    assert isinstance(ocean.created_on, datetime)
    assert ocean.created_on == datetime.fromisoformat("2025-01-15T09:30:00")
    assert ocean.estimated_arrival == datetime.fromisoformat("2025-02-01T12:00:00")
    assert ocean.actual_arrival == datetime.fromisoformat("2025-02-02T08:15:00")

    # Air omits ActualArrivalDate -> None, no error.
    assert air.actual_arrival is None


def test_empty_shipments_returns_empty_list():
    doc = f'<Shipments xmlns="{_NS}"/>'
    assert LxmlShipmentParser().parse(doc) == []


def test_malformed_xml_raises_validation_error():
    with pytest.raises(XmlValidationError):
        LxmlShipmentParser().parse("<Shipments><Broken></Shipments>")


def test_wrong_root_raises_validation_error():
    with pytest.raises(XmlValidationError):
        LxmlShipmentParser().parse(f'<Other xmlns="{_NS}"/>')
