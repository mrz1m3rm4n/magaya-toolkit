"""Domain read models for Magaya warehouse inventory.

Two levels, and the difference matters:

- **`ItemDefinition`** — the catalogue entry. What a thing IS: its part number,
  description, dimensions, and the running piece counts Magaya keeps for it.
- **`InventoryItem`** — one physical piece on a shelf. Where a thing IS: its
  serial number, warehouse location, the receipt it arrived on.

One definition has many items. `ItemDefinition.pieces` is Magaya's own running
total for the definition; the items are what make it up.

Read-only: these models are only ever populated from data the API returns.
Every field is optional — inventory records are sparsely filled.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from magaya_toolkit.domain.common import Measure, Package


class WarehouseLocation(BaseModel):
    """A place in the warehouse an item sits in (a rack, a zone, a bin)."""

    code: str | None = None
    description: str | None = None
    type: str | None = None
    warehouse_zone_name: str | None = None
    network_id: str | None = None
    is_disabled: bool | None = None


class ItemDefinition(BaseModel):
    """A warehouse item definition — the catalogue entry for a kind of thing.

    The piece counts are Magaya's own running totals and answer different
    questions: `pieces` is what is on hand, `available_pieces_for_sale` is what
    is actually sellable, and the compound-item counts cover pieces held inside
    kits rather than loose on a shelf.
    """

    guid: str | None = None
    type: str | None = None

    part_number: str | None = None
    description: str | None = None
    model: str | None = None
    item_type: str | None = None
    inventory_type: str | None = None

    pieces: int | None = None
    arriving_pieces: int | None = None
    pieces_in_compound_items: int | None = None
    arriving_pieces_in_compound_items: int | None = None
    available_pieces_for_sale: int | None = None

    unitary_value: Measure | None = None
    weight: Measure | None = None
    length: Measure | None = None
    width: Measure | None = None
    height: Measure | None = None
    volume: Measure | None = None

    package: Package | None = None
    sku_numbers: str | None = None
    manufacturer: str | None = None
    manufacturer_guid: str | None = None
    unit_of_measurement: str | None = None
    commodity_type: str | None = None
    commodity_type_code: str | None = None
    commodity_type_name: str | None = None
    created_on: datetime | None = None


class InventoryItem(BaseModel):
    """One physical inventory piece, as returned by inventory reads.

    Magaya inlines the whole `ItemDefinition` on every item, so
    `item_definition` is the real thing rather than a pointer — the catalogue
    entry travels with the piece.

    `location` is where the piece is now and `previous_location` where it came
    from, which together is how a stock move reads. `location_code` is the same
    code as `location.code`, kept because Magaya sends both.
    """

    guid: str | None = None
    type: str | None = None

    status: str | None = None
    description: str | None = None
    part_number: str | None = None
    model: str | None = None
    serial_number: str | None = None
    lot_number: str | None = None

    pieces: int | None = None
    piece_quantity: Measure | None = None
    is_summarized: bool | None = None

    warehouse_receipt_guid: str | None = None
    warehouse_receipt_number: str | None = None
    whr_item_id: str | None = None
    supplier_po_number: str | None = None
    entry_date: datetime | None = None

    location_code: str | None = None
    location: WarehouseLocation | None = None
    previous_location: WarehouseLocation | None = None

    package_name: str | None = None
    package: Package | None = None

    length: Measure | None = None
    width: Measure | None = None
    height: Measure | None = None
    weight: Measure | None = None
    volume: Measure | None = None
    volume_weight: Measure | None = None
    piece_weight: Measure | None = None
    piece_volume: Measure | None = None
    contained_pieces_weight_included: bool | None = None

    is_container: bool | None = None
    is_pallet: bool | None = None
    is_overstock: bool | None = None
    not_loaded: bool | None = None
    in_task: bool | None = None
    include_in_sed: bool | None = None

    item_definition: ItemDefinition | None = None
    up_item_guid: str | None = None
    version: str | None = None

    @property
    def moved(self) -> bool | None:
        """Whether the piece has been moved from where it first landed.

        None when either location is unknown.
        """
        if self.location is None or self.previous_location is None:
            return None
        if self.location.code is None or self.previous_location.code is None:
            return None
        return self.location.code != self.previous_location.code
