"""Unit tests for LxmlInventoryParser. No network access.

The documents mirror shapes captured from a live Magaya install. The assertion
that matters most is the shadowing one: an `<Item>` inlines its entire
`<ItemDefinition>`, and the two share `Description`, `Model`, `PartNumber`,
`Pieces` and every dimension element. The piece on the shelf and the catalogue
entry disagree on purpose in these fixtures so a regression is visible.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.inventory_parser import LxmlInventoryParser

_NS = "http://www.magaya.com/XMLSchema/V1"

_DEFINITIONS = f"""<?xml version="1.0" encoding="utf-8"?>
<ItemDefinitions xmlns="{_NS}">
  <ItemDefinition GUID="def-guid-1" Type="IV">
    <CreatedOn>2024-04-17T14:00:07-06:00</CreatedOn>
    <PartNumber>10001-01-11</PartNumber>
    <Description>TERGAL PREMIER</Description>
    <Model>Stetson</Model>
    <Pieces>41</Pieces>
    <PiecesInCompoundItems>2</PiecesInCompoundItems>
    <ArrivingPiecesInCompoundItems>0</ArrivingPiecesInCompoundItems>
    <AvailablePiecesForSale>39</AvailablePiecesForSale>
    <InventoryType>FIFO</InventoryType>
    <ItemType>StockItem</ItemType>
    <UnitaryValue Currency="MXN">125.50</UnitaryValue>
    <Weight Unit="kg">12.500</Weight>
    <Length Unit="m">58.00</Length>
    <Manufacturer GUID="man-guid-1">TEXTILES SA</Manufacturer>
  </ItemDefinition>
  <ItemDefinition GUID="def-guid-2" Type="IV">
    <PartNumber>SIN-STOCK</PartNumber>
    <Pieces>0</Pieces>
  </ItemDefinition>
</ItemDefinitions>"""

# The item and the definition it inlines disagree on every shared field.
_ITEMS = f"""<?xml version="1.0" encoding="utf-8"?>
<Items xmlns="{_NS}">
  <Item GUID="item-guid-1" Type="IV">
    <Version>3</Version>
    <Status>OnHand</Status>
    <Pieces>1</Pieces>
    <Description>ROLLO SUELTO</Description>
    <PartNumber>ITEM-PN</PartNumber>
    <Model>ItemModel</Model>
    <PieceQuantity>1.00</PieceQuantity>
    <IsSummarized>false</IsSummarized>
    <SerialNumber>305773</SerialNumber>
    <LotNumber>L-9</LotNumber>
    <WarehouseReceiptGUID>whr-guid-1</WarehouseReceiptGUID>
    <WarehouseReceiptNumber>WHR-100</WarehouseReceiptNumber>
    <WHRItemID>643</WHRItemID>
    <SupplierPONumber>CBHU8935481</SupplierPONumber>
    <PackageName>ROLLO</PackageName>
    <LocationCode>G101</LocationCode>
    <EntryDate>2024-05-02T09:15:00-06:00</EntryDate>
    <Length Unit="m">58.00</Length>
    <Weight Unit="kg">0.00</Weight>
    <Volume Unit="m3">1.25</Volume>
    <ContainedPiecesWeightIncluded>true</ContainedPiecesWeightIncluded>
    <IsContainer>false</IsContainer>
    <IsPallet>false</IsPallet>
    <Package>
      <Type>Roll</Type>
      <Code>ROL</Code>
      <Name>Rollo</Name>
    </Package>
    <Location Code="G101">
      <Description>RACK G</Description>
      <Type>Storage</Type>
      <NetworkID>34344</NetworkID>
      <WarehouseZoneName>WEPORT 1</WarehouseZoneName>
      <IsDisabled>false</IsDisabled>
    </Location>
    <PreviousLocation Code="F101">
      <Description>RACK F</Description>
      <Type>Storage</Type>
      <WarehouseZoneName>WEPORT 1</WarehouseZoneName>
    </PreviousLocation>
    <ItemDefinition GUID="def-guid-1" Type="IV">
      <PartNumber>10001-01-11</PartNumber>
      <Description>TERGAL PREMIER</Description>
      <Model>Stetson</Model>
      <Pieces>41</Pieces>
      <Weight Unit="kg">12.500</Weight>
      <Length Unit="m">99.99</Length>
    </ItemDefinition>
  </Item>
</Items>"""


@pytest.fixture
def parser() -> LxmlInventoryParser:
    return LxmlInventoryParser()


# -- definitions -----------------------------------------------------------


def test_parses_item_definitions_with_their_piece_counts(
    parser: LxmlInventoryParser,
) -> None:
    stocked, empty = parser.parse_definitions(_DEFINITIONS)

    assert stocked.guid == "def-guid-1"
    assert stocked.type == "IV"
    assert stocked.part_number == "10001-01-11"
    assert stocked.item_type == "StockItem"
    assert stocked.inventory_type == "FIFO"
    # The counts answer different questions and must not be conflated.
    assert stocked.pieces == 41
    assert stocked.available_pieces_for_sale == 39
    assert stocked.pieces_in_compound_items == 2

    assert empty.pieces == 0
    assert empty.description is None


def test_unitary_value_carries_a_currency_while_weight_carries_a_unit(
    parser: LxmlInventoryParser,
) -> None:
    """Two Measures on the same record read their unit from different attributes."""
    stocked, _ = parser.parse_definitions(_DEFINITIONS)

    assert stocked.unitary_value is not None
    assert stocked.unitary_value.value == Decimal("125.50")
    assert stocked.unitary_value.unit == "MXN"

    assert stocked.weight is not None
    assert stocked.weight.value == Decimal("12.500")
    assert stocked.weight.unit == "kg"


def test_manufacturer_keeps_both_its_name_and_guid(
    parser: LxmlInventoryParser,
) -> None:
    stocked, _ = parser.parse_definitions(_DEFINITIONS)

    assert stocked.manufacturer == "TEXTILES SA"
    assert stocked.manufacturer_guid == "man-guid-1"


def test_an_empty_definitions_document_is_an_empty_list(
    parser: LxmlInventoryParser,
) -> None:
    assert parser.parse_definitions(f'<ItemDefinitions xmlns="{_NS}"/>') == []


# -- items -----------------------------------------------------------------


def test_the_inlined_definition_does_not_shadow_the_items_own_fields(
    parser: LxmlInventoryParser,
) -> None:
    (item,) = parser.parse_items(_ITEMS)

    # Every one of these also exists inside the nested <ItemDefinition>.
    assert item.description == "ROLLO SUELTO"
    assert item.part_number == "ITEM-PN"
    assert item.model == "ItemModel"
    assert item.pieces == 1
    assert item.length is not None and item.length.value == Decimal("58.00")

    assert item.item_definition is not None
    assert item.item_definition.description == "TERGAL PREMIER"
    assert item.item_definition.pieces == 41
    assert item.item_definition.length is not None
    assert item.item_definition.length.value == Decimal("99.99")


def test_parses_both_locations_from_their_code_attribute(
    parser: LxmlInventoryParser,
) -> None:
    (item,) = parser.parse_items(_ITEMS)

    assert item.location is not None
    assert item.location.code == "G101"
    assert item.location.description == "RACK G"
    assert item.location.warehouse_zone_name == "WEPORT 1"
    assert item.location.is_disabled is False

    assert item.previous_location is not None
    assert item.previous_location.code == "F101"
    # Magaya sends the flat code too; both agree.
    assert item.location_code == "G101"


def test_moved_compares_the_current_location_against_the_previous_one(
    parser: LxmlInventoryParser,
) -> None:
    (item,) = parser.parse_items(_ITEMS)

    assert item.moved is True


def test_moved_is_unknown_without_both_locations(
    parser: LxmlInventoryParser,
) -> None:
    doc = _ITEMS.replace('<PreviousLocation Code="F101">', "<PreviousLocation>").replace(
        "</PreviousLocation>", "</PreviousLocation>"
    )

    (item,) = parser.parse_items(doc)

    assert item.moved is None


def test_parses_the_items_own_package_and_receipt_trail(
    parser: LxmlInventoryParser,
) -> None:
    (item,) = parser.parse_items(_ITEMS)

    assert item.status == "OnHand"
    assert item.serial_number == "305773"
    assert item.lot_number == "L-9"
    assert item.warehouse_receipt_guid == "whr-guid-1"
    assert item.warehouse_receipt_number == "WHR-100"
    assert item.supplier_po_number == "CBHU8935481"
    assert item.entry_date is not None
    assert item.package is not None
    assert item.package.code == "ROL"
    assert item.package_name == "ROLLO"


def test_a_definition_with_no_stock_is_an_empty_list(
    parser: LxmlInventoryParser,
) -> None:
    assert parser.parse_items(f'<Items xmlns="{_NS}"/>') == []


# -- the VIN lookup's inferred shape ---------------------------------------


def test_parses_a_single_item_document(parser: LxmlInventoryParser) -> None:
    doc = f'<Item xmlns="{_NS}" GUID="veh-1" Type="IV"><SerialNumber>V1</SerialNumber></Item>'

    item = parser.parse_one_item(doc)

    assert item.guid == "veh-1"
    assert item.serial_number == "V1"


def test_an_unexpected_vin_shape_fails_loudly_rather_than_silently(
    parser: LxmlInventoryParser,
) -> None:
    """The `<Item>` root is inferred; a different one must be obvious, not silent."""
    with pytest.raises(XmlValidationError, match="Item"):
        parser.parse_one_item(f'<Vehicle xmlns="{_NS}"><VIN>X</VIN></Vehicle>')


# -- failure modes ---------------------------------------------------------


def test_rejects_a_document_with_the_wrong_root(parser: LxmlInventoryParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse_items(_DEFINITIONS)


def test_rejects_malformed_xml(parser: LxmlInventoryParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse_definitions("<ItemDefinitions><ItemDefinition>")
