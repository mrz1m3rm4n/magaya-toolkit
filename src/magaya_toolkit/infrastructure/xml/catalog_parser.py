"""lxml-based parser for the Magaya catalog/definition documents.

Parses `<Currencies>`, `<EventDefinitions>`, `<AccountDefinitions>`,
`<ChargeDefinitions>`, `<CustomChargeDefinitions>` and `<Ports>` into the
`domain.catalog` read models.

Same two invariants as the other parsers:

1. Namespace. The documents are namespaced under
   ``http://www.magaya.com/XMLSchema/V1``. We read elements by local-name so a
   missing/mismatched namespace prefix never hides a field.
2. Direct children only. The same tag names (`Name`, `Type`, `Currency`, …)
   reappear inside nested elements — `<AccountDefinition>` embeds a
   `<Currency>` and a whole `<ParentAccount>` — so a record's own fields are
   read from its *direct* children only.

Two shapes deserve a note, both confirmed against a live Magaya install:

- `<Port>` carries `<Method>` REPEATED (0 to 4 times: Air/Ocean/Ground/Mail),
  so `Port.methods` is a list.
- `<AccountDefinition>` nests its parent recursively via `<ParentAccount>`.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from lxml import etree

from magaya_toolkit.domain.catalog import (
    AccountDefinition,
    ChargeDefinition,
    Currency,
    EventDefinition,
    Port,
)
from magaya_toolkit.domain.common import Measure
from magaya_toolkit.domain.errors import XmlValidationError

_CURRENCIES_ROOT = "Currencies"
_EVENT_DEFINITIONS_ROOT = "EventDefinitions"
_ACCOUNT_DEFINITIONS_ROOT = "AccountDefinitions"
_CHARGE_DEFINITIONS_ROOT = "ChargeDefinitions"
_CUSTOM_CHARGE_DEFINITIONS_ROOT = "CustomChargeDefinitions"
_PORTS_ROOT = "Ports"

# How deep to follow <ParentAccount> before giving up. The chart of accounts is
# a shallow tree; this only guards against a malformed self-referential document.
_MAX_ACCOUNT_DEPTH = 16


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlCatalogParser:
    """Parse Magaya catalog/definition XML into read models."""

    # -- documents ---------------------------------------------------------

    def parse_currencies(self, currency_list_xml: str | bytes) -> list[Currency]:
        root = self._root(currency_list_xml, _CURRENCIES_ROOT)
        return [self._to_currency(element) for element in self._items(root)]

    def parse_event_definitions(
        self, event_definition_list_xml: str | bytes
    ) -> list[EventDefinition]:
        root = self._root(event_definition_list_xml, _EVENT_DEFINITIONS_ROOT)
        return [self._to_event_definition(element) for element in self._items(root)]

    def parse_account_definitions(
        self, account_list_xml: str | bytes
    ) -> list[AccountDefinition]:
        root = self._root(account_list_xml, _ACCOUNT_DEFINITIONS_ROOT)
        return [self._to_account_definition(element) for element in self._items(root)]

    def parse_charge_definitions(self, service_list_xml: str | bytes) -> list[ChargeDefinition]:
        root = self._root(service_list_xml, _CHARGE_DEFINITIONS_ROOT)
        return [self._to_charge_definition(element) for element in self._items(root)]

    def parse_custom_charge_definitions(
        self, charge_list_xml: str | bytes
    ) -> list[ChargeDefinition]:
        """Parse a client's `<CustomChargeDefinitions>` document.

        Items are read with the same reader as `<ChargeDefinitions>`: the two
        documents describe the same thing, one globally and one overridden per
        client. A client with no custom charges yields an empty root, and this
        returns [].
        """
        root = self._root(charge_list_xml, _CUSTOM_CHARGE_DEFINITIONS_ROOT)
        return [self._to_charge_definition(element) for element in self._items(root)]

    def parse_ports(self, ports_list_xml: str | bytes) -> list[Port]:
        root = self._root(ports_list_xml, _PORTS_ROOT)
        return [self._to_port(element) for element in self._items(root)]

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

    @staticmethod
    def _items(root: etree._Element) -> list[etree._Element]:
        """Direct element children of the document root (comments skipped)."""
        return [child for child in root if isinstance(child.tag, str)]

    # -- element -> domain -------------------------------------------------

    def _to_currency(self, element: etree._Element) -> Currency:
        children = self._children(element)
        return Currency(
            # `Code` is an attribute of <Currency>, not a child element.
            code=(element.get("Code") or "").strip() or None,
            name=self._text(children, "Name"),
            exchange_rate=self._decimal(children, "ExchangeRate"),
            decimal_places=self._int(children, "DecimalPlaces"),
            is_home_currency=self._bool(children, "IsHomeCurrency"),
        )

    def _to_event_definition(self, element: etree._Element) -> EventDefinition:
        children = self._children(element)
        return EventDefinition(
            name=self._text(children, "Name"),
            include_in_tracking=self._bool(children, "IncludeInTracking"),
            details=self._text(children, "Details"),
        )

    def _to_account_definition(
        self, element: etree._Element, _depth: int = 0
    ) -> AccountDefinition:
        children = self._children(element)
        parent_node = children.get("ParentAccount")
        parent = None
        if parent_node is not None and _depth < _MAX_ACCOUNT_DEPTH:
            parent = self._to_account_definition(parent_node, _depth + 1)
        return AccountDefinition(
            type=self._text(children, "Type"),
            name=self._text(children, "Name"),
            number=self._text(children, "Number"),
            currency=self._currency_child(children),
            parent_account=parent,
        )

    def _to_charge_definition(self, element: etree._Element) -> ChargeDefinition:
        children = self._children(element)
        account_node = children.get("AccountDefinition")
        tax_node = children.get("TaxDefinition")
        return ChargeDefinition(
            type=self._text(children, "Type"),
            code=self._text(children, "Code"),
            description=self._text(children, "Description"),
            # <Amount Currency="MXN">0.00</Amount> — value in text, code in attr.
            amount=self._measure(children, "Amount", "Currency"),
            currency=self._currency_child(children),
            account_definition=(
                self._to_account_definition(account_node) if account_node is not None else None
            ),
            tax_definition_name=(
                self._text(self._children(tax_node), "Name") if tax_node is not None else None
            ),
            iata_code=self._text(children, "IATACode"),
            notes=self._text(children, "Notes"),
            enforce_3rd_party_billing=self._bool(children, "Enforce3rdPartyBilling"),
        )

    def _to_port(self, element: etree._Element) -> Port:
        children = self._children(element)
        # <Method> repeats (0..4 per port), so collect every occurrence in order
        # instead of reading a single child.
        methods = [
            child.text.strip()
            for child in element
            if isinstance(child.tag, str)
            and _local_name(child) == "Method"
            and child.text is not None
            and child.text.strip()
        ]
        return Port(
            code=(element.get("Code") or "").strip() or None,
            name=self._text(children, "Name"),
            # <Country Code="AE">UNITED ARAB EMIRATES</Country> — name in text.
            country=self._text(children, "Country"),
            country_code=self._attr(children, "Country", "Code"),
            methods=methods,
            subdivision=self._text(children, "Subdivision"),
            remarks=self._text(children, "Remarks"),
        )

    def _currency_child(self, children: dict[str, etree._Element]) -> Currency | None:
        """Parse a nested `<Currency Code="…">` element, if present."""
        node = children.get("Currency")
        if node is None:
            return None
        return self._to_currency(node)

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
        return text.lower() == "true"

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
    def _decimal(cls, children: dict[str, etree._Element], name: str) -> Decimal | None:
        text = cls._text(children, name)
        if text is None:
            return None
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def _measure(
        cls, children: dict[str, etree._Element], name: str, unit_attr: str
    ) -> Measure | None:
        value = cls._decimal(children, name)
        if value is None:
            return None
        return Measure(value=value, unit=cls._attr(children, name, unit_attr))
