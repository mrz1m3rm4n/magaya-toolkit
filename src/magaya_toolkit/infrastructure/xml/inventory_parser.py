"""lxml-based parser for the Magaya inventory documents.

Parses `<ItemDefinitions>` and `<Items>` into the `domain.inventory` read
models, plus the single `<Item>` a VIN lookup answers with.

Same two invariants as the other parsers:

1. Namespace. Documents are namespaced under
   ``http://www.magaya.com/XMLSchema/V1``; elements are read by local-name.
2. Direct children only. An `<Item>` inlines its whole `<ItemDefinition>`,
   which repeats `Description`, `Model`, `PartNumber`, `Pieces` and the
   dimension elements. The item's own values are read from its direct children
   so the definition's cannot shadow them.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from magaya_toolkit.domain.common import Measure, Package
from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.domain.inventory import (
    InventoryItem,
    ItemDefinition,
    WarehouseLocation,
)

_ITEM_DEFINITIONS_ROOT = "ItemDefinitions"
_ITEMS_ROOT = "Items"
_ITEM_ROOT = "Item"


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlInventoryParser:
    """Parse Magaya inventory XML into read models."""

    # -- documents ---------------------------------------------------------

    def parse_definitions(self, def_list_xml: str | bytes) -> list[ItemDefinition]:
        """Parse an `<ItemDefinitions>` document. An empty one returns []."""
        root = self._root(def_list_xml, _ITEM_DEFINITIONS_ROOT)
        return [
            self._to_definition(element)
            for element in root
            if isinstance(element.tag, str)
        ]

    def parse_items(self, item_list_xml: str | bytes) -> list[InventoryItem]:
        """Parse an `<Items>` document. A definition with no stock returns []."""
        root = self._root(item_list_xml, _ITEMS_ROOT)
        return [
            self._to_item(element) for element in root if isinstance(element.tag, str)
        ]

    def parse_one_item(self, item_xml: str | bytes) -> InventoryItem:
        """Parse a single `<Item>` document, the way a VIN lookup answers.

        NOTE: this shape is inferred, not confirmed. `GetItemFromVIN` could only
        be exercised against a Magaya install with no vehicles in it, so only
        its not-found path was seen for real. The `<Item>` root follows the
        pattern the rest of the API uses for single-record reads; if a vehicle
        install disagrees, this raises `XmlValidationError` naming what it got.
        """
        root = self._root(item_xml, _ITEM_ROOT)
        return self._to_item(root)

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def _root(xml: str | bytes, expected_root: str) -> etree._Element:
        raw = xml.encode("utf-8") if isinstance(xml, str) else xml
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                f"The <{expected_root}> document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc
        if _local_name(root) != expected_root:
            raise XmlValidationError(
                f"Expected an <{expected_root}> root, got <{_local_name(root)}>.",
            )
        return root

    # -- element -> domain -------------------------------------------------

    def _to_definition(self, element: etree._Element) -> ItemDefinition:
        children = self._children(element)
        package_node = children.get("Package")
        return ItemDefinition(
            guid=element.get("GUID"),
            type=element.get("Type"),
            part_number=self._text(children, "PartNumber"),
            description=self._text(children, "Description"),
            model=self._text(children, "Model"),
            item_type=self._text(children, "ItemType"),
            inventory_type=self._text(children, "InventoryType"),
            pieces=self._int(children, "Pieces"),
            arriving_pieces=self._int(children, "ArrivingPieces"),
            pieces_in_compound_items=self._int(children, "PiecesInCompoundItems"),
            arriving_pieces_in_compound_items=self._int(
                children, "ArrivingPiecesInCompoundItems"
            ),
            available_pieces_for_sale=self._int(children, "AvailablePiecesForSale"),
            # <UnitaryValue Currency="MXN"> — money, not a unit of measure.
            unitary_value=self._measure(children, "UnitaryValue", "Currency"),
            weight=self._measure(children, "Weight", "Unit"),
            length=self._measure(children, "Length", "Unit"),
            width=self._measure(children, "Width", "Unit"),
            height=self._measure(children, "Height", "Unit"),
            volume=self._measure(children, "Volume", "Unit"),
            package=(
                self._package(package_node) if package_node is not None else None
            ),
            sku_numbers=self._text(children, "SKUNumbers"),
            manufacturer=self._text(children, "Manufacturer"),
            manufacturer_guid=self._attr(children, "Manufacturer", "GUID"),
            unit_of_measurement=self._text(children, "UnitOfMeasurement"),
            commodity_type=self._text(children, "CommodityType"),
            commodity_type_code=self._attr(children, "CommodityType", "Code"),
            commodity_type_name=self._text(children, "CommodityTypeName"),
            created_on=self._datetime(children, "CreatedOn"),
        )

    def _to_item(self, element: etree._Element) -> InventoryItem:
        children = self._children(element)
        definition_node = children.get("ItemDefinition")
        package_node = children.get("Package")
        return InventoryItem(
            guid=element.get("GUID"),
            type=element.get("Type"),
            status=self._text(children, "Status"),
            description=self._text(children, "Description"),
            part_number=self._text(children, "PartNumber"),
            model=self._text(children, "Model"),
            serial_number=self._text(children, "SerialNumber"),
            lot_number=self._text(children, "LotNumber"),
            pieces=self._int(children, "Pieces"),
            piece_quantity=self._measure(children, "PieceQuantity", "Unit"),
            is_summarized=self._bool(children, "IsSummarized"),
            warehouse_receipt_guid=self._text(children, "WarehouseReceiptGUID"),
            warehouse_receipt_number=self._text(children, "WarehouseReceiptNumber"),
            whr_item_id=self._text(children, "WHRItemID"),
            supplier_po_number=self._text(children, "SupplierPONumber"),
            entry_date=self._datetime(children, "EntryDate"),
            location_code=self._text(children, "LocationCode"),
            location=self._location(children.get("Location")),
            previous_location=self._location(children.get("PreviousLocation")),
            package_name=self._text(children, "PackageName"),
            package=(
                self._package(package_node) if package_node is not None else None
            ),
            length=self._measure(children, "Length", "Unit"),
            width=self._measure(children, "Width", "Unit"),
            height=self._measure(children, "Height", "Unit"),
            weight=self._measure(children, "Weight", "Unit"),
            volume=self._measure(children, "Volume", "Unit"),
            volume_weight=self._measure(children, "VolumeWeight", "Unit"),
            piece_weight=self._measure(children, "PieceWeight", "Unit"),
            piece_volume=self._measure(children, "PieceVolume", "Unit"),
            contained_pieces_weight_included=self._bool(
                children, "ContainedPiecesWeightIncluded"
            ),
            is_container=self._bool(children, "IsContainer"),
            is_pallet=self._bool(children, "IsPallet"),
            is_overstock=self._bool(children, "IsOverstock"),
            not_loaded=self._bool(children, "NotLoaded"),
            in_task=self._bool(children, "InTask"),
            include_in_sed=self._bool(children, "IncludeInSED"),
            item_definition=(
                self._to_definition(definition_node)
                if definition_node is not None
                else None
            ),
            up_item_guid=self._text(children, "UpItemGUID"),
            version=self._text(children, "Version"),
        )

    def _location(self, node: etree._Element | None) -> WarehouseLocation | None:
        if node is None:
            return None
        children = self._children(node)
        return WarehouseLocation(
            # <Location Code="G101"> — the code is an attribute.
            code=(node.get("Code") or "").strip() or None,
            description=self._text(children, "Description"),
            type=self._text(children, "Type"),
            warehouse_zone_name=self._text(children, "WarehouseZoneName"),
            network_id=self._text(children, "NetworkID"),
            is_disabled=self._bool(children, "IsDisabled"),
        )

    def _package(self, node: etree._Element) -> Package:
        children = self._children(node)
        methods_node = children.get("Methods")
        methods: list[str] = []
        if methods_node is not None:
            methods = [
                child.text.strip()
                for child in methods_node
                if isinstance(child.tag, str)
                and _local_name(child) == "Method"
                and child.text is not None
                and child.text.strip()
            ]
        return Package(
            type=self._text(children, "Type"),
            code=self._text(children, "Code"),
            name=self._text(children, "Name"),
            container_code=self._text(children, "ContainerCode"),
            container_equip_type=self._text(children, "ContainerEquipType"),
            methods=methods,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _children(element: etree._Element) -> dict[str, etree._Element]:
        """Map direct-child local-names to elements (last occurrence wins)."""
        children: dict[str, etree._Element] = {}
        for child in element:
            if isinstance(child.tag, str):
                children[_local_name(child)] = child
        return children

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
    def _bool(cls, children: dict[str, etree._Element], name: str) -> bool | None:
        text = cls._text(children, name)
        if text is None:
            return None
        return text.lower() in ("true", "1")

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
    def _datetime(cls, children: dict[str, etree._Element], name: str) -> datetime | None:
        text = cls._text(children, name)
        if text is None:
            return None
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
