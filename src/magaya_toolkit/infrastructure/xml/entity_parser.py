"""lxml-based implementation of the `EntityParser` port.

Parses the Magaya `<Entities>` and `<EntityContacts>` documents into `Entity`
and `EntityContact` domain read models.

Two invariants worth spelling out (mirroring the shipment parser):

1. Namespace. The documents are namespaced under
   ``http://www.magaya.com/XMLSchema/V1`` (singular "XMLSchema"). We read
   elements by local-name so a missing/mismatched namespace prefix never hides
   a field.
2. Direct children only. An entity element carries its own fields as *direct*
   children, but the same tag names also appear inside nested complex elements
   (e.g. `RelatedEntities`). We iterate only direct children so a nested field
   can never be mistaken for the entity's own.

An entity's `kind` is derived from its element local-name (`Client`, `Carrier`,
`Vendor`, …). `<Address>`/`<BillingAddress>` sub-elements are parsed into the
`Address` model — all `<Street>` lines are collected into a list.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from magaya_toolkit.domain.common import Address, Measure
from magaya_toolkit.domain.entity import Entity, EntityContact
from magaya_toolkit.domain.errors import XmlValidationError

# Expected root local-names for the two Magaya entity documents.
_ENTITIES_ROOT_LOCAL_NAME = "Entities"
_CONTACTS_ROOT_LOCAL_NAME = "EntityContacts"


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlEntityParser:
    """Parse Magaya `<Entities>`/`<EntityContacts>` XML into read models."""

    def parse_entities(self, entity_list_xml: str | bytes) -> list[Entity]:
        root = self._root(entity_list_xml, _ENTITIES_ROOT_LOCAL_NAME)
        entities: list[Entity] = []
        # Direct children of <Entities> are the individual entity elements; the
        # child tag (Client/Carrier/Vendor/…) is the entity kind.
        for element in root:
            if not isinstance(element.tag, str):
                continue
            entities.append(self._to_entity(element))
        return entities

    def parse_contacts(self, contact_list_xml: str | bytes) -> list[EntityContact]:
        root = self._root(contact_list_xml, _CONTACTS_ROOT_LOCAL_NAME)
        contacts: list[EntityContact] = []
        for element in root:
            if not isinstance(element.tag, str):
                continue
            contacts.append(self._to_contact(element))
        return contacts

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
                f"Expected a <{expected_root}> root, got <{_local_name(root)}>.",
            )
        return root

    # -- element -> domain -------------------------------------------------

    def _to_entity(self, element: etree._Element) -> Entity:
        children = self._children(element)
        return Entity(
            guid=element.get("GUID"),
            kind=_local_name(element),
            name=self._text(children, "Name"),
            entity_id=self._text(children, "EntityID"),
            account_number=self._text(children, "AccountNumber"),
            type=self._text(children, "Type"),
            email=self._text(children, "Email"),
            phone=self._text(children, "Phone"),
            contact_first_name=self._text(children, "ContactFirstName"),
            contact_last_name=self._text(children, "ContactLastName"),
            exporter_id=self._text(children, "ExporterID"),
            exporter_id_type=self._text(children, "ExporterIDType"),
            created_on=self._datetime(children, "CreatedOn"),
            is_prepaid=self._bool(children, "IsPrepaid"),
            is_inactive=self._bool(children, "IsInactive"),
            balance=self._measure(children, "Balance", "Currency"),
            address=self._address(children.get("Address")),
            billing_address=self._address(children.get("BillingAddress")),
        )

    def _to_contact(self, element: etree._Element) -> EntityContact:
        children = self._children(element)
        address = self._address(children.get("Address"))
        return EntityContact(
            guid=element.get("GUID"),
            name=self._text(children, "Name"),
            type=self._text(children, "Type"),
            created_on=self._datetime(children, "CreatedOn"),
            contact_name=address.contact_name if address is not None else None,
            contact_phone=address.contact_phone if address is not None else None,
            contact_email=address.contact_email if address is not None else None,
        )

    def _address(self, node: etree._Element | None) -> Address | None:
        if node is None:
            return None
        children = self._children(node)
        # <Street> may repeat: collect every non-empty street line, in order.
        streets = [
            child.text.strip()
            for child in node
            if isinstance(child.tag, str)
            and _local_name(child) == "Street"
            and child.text is not None
            and child.text.strip()
        ]
        return Address(
            street=streets,
            city=self._text(children, "City"),
            state=self._text(children, "State"),
            zip_code=self._text(children, "ZipCode"),
            country=self._text(children, "Country"),
            country_code=self._attr(children, "Country", "Code"),
            contact_name=self._text(children, "ContactName"),
            contact_phone=self._text(children, "ContactPhone"),
            contact_email=self._text(children, "ContactEmail"),
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
