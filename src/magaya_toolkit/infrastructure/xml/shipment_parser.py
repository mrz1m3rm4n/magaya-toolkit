"""lxml-based implementation of the `ShipmentParser` port.

Parses the Magaya `<Shipments>` document into `Shipment` domain read models.

Two invariants worth spelling out:

1. Namespace. The document is namespaced under
   ``http://www.magaya.com/XMLSchema/V1`` (singular "XMLSchema"). We read
   elements by local-name so a missing/mismatched namespace prefix never hides
   a field.
2. Direct children only. A shipment element carries its own fields as *direct*
   children, but the same tag names (e.g. ``Number``) also appear deep inside
   ``<Items>``/``<Events>``. We iterate only direct children so a nested
   ``<Number>`` can never be mistaken for the shipment's own number.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.domain.shipment import Measure, Shipment

# Expected root local-name for a Magaya transaction batch of shipments.
_ROOT_LOCAL_NAME = "Shipments"

# Map a shipment element local-name to the domain `mode`. Anything else falls
# back to the local-name itself.
_MODE_BY_LOCAL_NAME = {
    "OceanShipment": "Ocean",
    "AirShipment": "Air",
}


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlShipmentParser:
    """Parse Magaya `<Shipments>` XML into `Shipment` read models."""

    def parse(self, trans_list_xml: str | bytes) -> list[Shipment]:
        raw = trans_list_xml.encode("utf-8") if isinstance(trans_list_xml, str) else trans_list_xml
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                "The shipments document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc

        if _local_name(root) != _ROOT_LOCAL_NAME:
            raise XmlValidationError(
                f"Expected a <{_ROOT_LOCAL_NAME}> root, got <{_local_name(root)}>.",
            )

        shipments: list[Shipment] = []
        # Direct children of <Shipments> are the individual shipment elements.
        for element in root:
            # Skip comments/processing instructions.
            if not isinstance(element.tag, str):
                continue
            shipments.append(self._to_shipment(element))
        return shipments

    def parse_one(self, trans_xml: str | bytes) -> Shipment:
        """Parse a single-transaction `GetTransaction` response into a `Shipment`.

        Unlike `parse`, whose root is a `<Shipments>` batch, `GetTransaction`
        returns the shipment element itself as the root (e.g. `<OceanShipment>`
        or `<AirShipment>`), so we hand the root straight to `_to_shipment`.
        Raises `XmlValidationError` on malformed XML or on being handed a
        `<Shipments>` batch by mistake.
        """
        raw = trans_xml.encode("utf-8") if isinstance(trans_xml, str) else trans_xml
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                "The transaction document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc

        if _local_name(root) == _ROOT_LOCAL_NAME:
            raise XmlValidationError(
                f"Expected a single shipment element, got a <{_ROOT_LOCAL_NAME}> batch. "
                "Use `parse` for batch documents.",
            )
        return self._to_shipment(root)

    # -- element -> domain -------------------------------------------------

    def _to_shipment(self, element: etree._Element) -> Shipment:
        # Read ONLY direct children into a local-name -> element map. The last
        # occurrence wins, which is fine for the flat direct-child fields.
        children: dict[str, etree._Element] = {}
        for child in element:
            if isinstance(child.tag, str):
                children[_local_name(child)] = child

        local = _local_name(element)
        mode = _MODE_BY_LOCAL_NAME.get(local, local)

        return Shipment(
            guid=element.get("GUID"),
            number=self._text(children, "Number") or "",
            mode=mode,
            type_code=element.get("Type"),
            direction=self._text(children, "Direction"),
            status=self._text(children, "Status"),
            service=self._text(children, "Service"),
            layout_type=self._text(children, "LayoutType"),
            created_on=self._datetime(children, "CreatedOn"),
            created_by=self._text(children, "CreatedByName"),
            shipper_name=self._text(children, "ShipperName"),
            consignee_name=self._text(children, "ConsigneeName"),
            carrier_name=self._text(children, "CarrierName"),
            destination_agent_name=self._text(children, "DestinationAgentName"),
            origin_port=self._attr(children, "OriginPort", "Code"),
            destination_port=self._attr(children, "DestinationPort", "Code"),
            delivery_port=self._attr(children, "DeliveryPort", "Code"),
            description_of_goods=self._text(children, "DescriptionOfGoods"),
            total_pieces=self._int(children, "TotalPieces"),
            total_weight=self._measure(children, "TotalWeight", "Unit"),
            total_volume=self._measure(children, "TotalVolume", "Unit"),
            total_value=self._measure(children, "TotalValue", "Currency"),
            estimated_arrival=self._datetime(children, "EstimatedArrivalDate"),
            actual_arrival=self._datetime(children, "ActualArrivalDate"),
            estimated_departure=self._datetime(children, "EstimatedDepartureDate"),
            actual_departure=self._datetime(children, "ActualDepartureDate"),
            booking_number=self._text(children, "BookingNumber"),
            master_number=self._text(children, "MasterNumber"),
            master_guid=self._text(children, "MasterGUID"),
            mode_of_transport_code=self._text(children, "ModeOfTransportCode"),
            has_attachments=self._bool(children, "HasAttachments"),
        )

    # -- field readers -----------------------------------------------------

    @staticmethod
    def _text(children: dict[str, etree._Element], name: str) -> str | None:
        node = children.get(name)
        if node is None or node.text is None:
            return None
        text = node.text.strip()
        return text or None

    @staticmethod
    def _attr(children: dict[str, etree._Element], name: str, attr: str) -> str | None:
        node = children.get(name)
        if node is None:
            return None
        value = node.get(attr)
        if value is None:
            return None
        value = value.strip()
        return value or None

    @classmethod
    def _int(cls, children: dict[str, etree._Element], name: str) -> int | None:
        text = cls._text(children, name)
        if text is None:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    @classmethod
    def _bool(cls, children: dict[str, etree._Element], name: str) -> bool | None:
        text = cls._text(children, name)
        if text is None:
            return None
        return text.lower() == "true"

    @classmethod
    def _datetime(cls, children: dict[str, etree._Element], name: str) -> datetime | None:
        text = cls._text(children, name)
        if text is None:
            return None
        # Magaya emits ISO-8601-ish timestamps; accept a trailing "Z" too.
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None

    @classmethod
    def _measure(
        cls, children: dict[str, etree._Element], name: str, unit_attr: str
    ) -> Measure | None:
        text = cls._text(children, name)
        if text is None:
            return None
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        return Measure(value=value, unit=cls._attr(children, name, unit_attr))
