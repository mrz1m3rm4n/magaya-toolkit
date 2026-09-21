"""lxml-based parser for the Magaya rate documents.

Parses `<StandardRates>`, `<ClientRates>` and `<CarrierRates>` into `Rate` read
models. The three reads return the same `<Rate>` element under three different
document roots, so one parser serves all of them.

Same two invariants as the other parsers:

1. Namespace. Documents are namespaced under
   ``http://www.magaya.com/XMLSchema/V1``; elements are read by local-name.
2. Direct children only. A rate inlines whole object graphs — the carrier's
   full entity record, the charge's account and tax authority — and those
   repeat tag names like `<Type>`, `<Name>` and `<Currency>`. A rate's own
   fields are read from its *direct* children only.

`<Currency>` and `<ChargeDefinition>` are read through `LxmlCatalogParser`,
which already models them for the catalog documents.

One limitation worth stating: Magaya prices a rate by `ApplyBy`, which can be
Package, Weight, Volume, Pieces, Formula or Unknown. Only `<PackageRates>` is
parsed here — it is the only variant that could be confirmed against a live
install. Rates priced another way still parse, with `package_rates` empty.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from magaya_toolkit.domain.common import Measure
from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.domain.rate import (
    ApplicableModes,
    ModeOfTransportation,
    Package,
    PackageRate,
    PartyRef,
    Rate,
)
from magaya_toolkit.infrastructure.xml.catalog_parser import LxmlCatalogParser

# One root per rate read; `parse` accepts any of them.
_RATE_ROOTS = ("StandardRates", "ClientRates", "CarrierRates")


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlRateParser:
    """Parse Magaya rate XML into `Rate` read models."""

    def __init__(self) -> None:
        self._catalog = LxmlCatalogParser()

    def parse(self, rate_list_xml: str | bytes) -> list[Rate]:
        """Parse any of the three rate documents into `Rate` objects.

        Raises `XmlValidationError` if the input is not a well-formed
        `<StandardRates>`, `<ClientRates>` or `<CarrierRates>` document. An
        empty document returns [].
        """
        root = self._root(rate_list_xml)
        return [
            self._to_rate(element) for element in root if isinstance(element.tag, str)
        ]

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def _root(xml: str | bytes) -> etree._Element:
        raw = xml.encode("utf-8") if isinstance(xml, str) else xml
        expected = " / ".join(f"<{name}>" for name in _RATE_ROOTS)
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                f"The rate document ({expected}) is not well-formed XML.",
                problems=[str(exc)],
            ) from exc
        if _local_name(root) not in _RATE_ROOTS:
            raise XmlValidationError(
                f"Expected a {expected} root, got <{_local_name(root)}>.",
            )
        return root

    # -- element -> domain -------------------------------------------------

    def _to_rate(self, element: etree._Element) -> Rate:
        children = self._children(element)
        charge_node = children.get("ChargeDefinition")
        currency_node = children.get("Currency")
        modes_node = children.get("ApplicableModesOfTransportation")
        return Rate(
            guid=element.get("GUID"),
            type=self._text(children, "Type"),
            charge_definition=(
                self._catalog.charge_definition_from_element(charge_node)
                if charge_node is not None
                else None
            ),
            carrier=self._party(children.get("Carrier")),
            services=self._repeated(children.get("Services"), "Service"),
            # <OriginCountry Code="MX">MEXICO</OriginCountry> — name in text.
            origin_country=self._text(children, "OriginCountry"),
            origin_country_code=self._attr(children, "OriginCountry", "Code"),
            destination_country=self._text(children, "DestinationCountry"),
            destination_country_code=self._attr(children, "DestinationCountry", "Code"),
            applicable_modes=(
                self._applicable_modes(modes_node) if modes_node is not None else None
            ),
            currency=(
                self._catalog.currency_from_element(currency_node)
                if currency_node is not None
                else None
            ),
            apply_by=self._text(children, "ApplyBy"),
            package_rates=self._package_rates(children.get("PackageRates")),
            frequency=self._text(children, "Frequency"),
            created_on=self._datetime(children, "CreatedOn"),
            use_gross_weight=self._bool(children, "UseGrossWeight"),
            is_hazardous=self._bool(children, "IsHazardous"),
            is_automatic_create_charge=self._bool(children, "IsAutomaticCreateCharge"),
        )

    def _party(self, node: etree._Element | None) -> PartyRef | None:
        """Read only the pointer out of an inlined entity record."""
        if node is None:
            return None
        children = self._children(node)
        return PartyRef(
            guid=node.get("GUID"),
            name=self._text(children, "Name"),
            type=self._text(children, "Type"),
        )

    def _applicable_modes(self, node: etree._Element) -> ApplicableModes:
        children = self._children(node)
        modes_node = children.get("ModesOfTransportation")
        modes: list[ModeOfTransportation] = []
        if modes_node is not None:
            for child in modes_node:
                if not isinstance(child.tag, str):
                    continue
                if _local_name(child) != "ModeOfTransportation":
                    continue
                mode_children = self._children(child)
                modes.append(
                    ModeOfTransportation(
                        code=child.get("Code"),
                        description=self._text(mode_children, "Description"),
                        method=self._text(mode_children, "Method"),
                    )
                )
        return ApplicableModes(
            all_methods_included=self._bool(children, "AllMethodsIncluded"),
            methods=self._repeated(children.get("Methods"), "Method"),
            modes=modes,
        )

    def _package_rates(self, node: etree._Element | None) -> list[PackageRate]:
        if node is None:
            return []
        rates: list[PackageRate] = []
        for child in node:
            if not isinstance(child.tag, str) or _local_name(child) != "PackageRate":
                continue
            children = self._children(child)
            package_node = children.get("Package")
            rates.append(
                PackageRate(
                    package=(
                        self._package(package_node) if package_node is not None else None
                    ),
                    # <Price Currency="MXN">50.00</Price>
                    price=self._measure(children, "Price", "Currency"),
                )
            )
        return rates

    def _package(self, node: etree._Element) -> Package:
        children = self._children(node)
        return Package(
            type=self._text(children, "Type"),
            code=self._text(children, "Code"),
            name=self._text(children, "Name"),
            container_code=self._text(children, "ContainerCode"),
            container_equip_type=self._text(children, "ContainerEquipType"),
            methods=self._repeated(children.get("Methods"), "Method"),
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _repeated(node: etree._Element | None, child_name: str) -> list[str]:
        """Collect the text of every `<child_name>` directly under `node`."""
        if node is None:
            return []
        return [
            child.text.strip()
            for child in node
            if isinstance(child.tag, str)
            and _local_name(child) == child_name
            and child.text is not None
            and child.text.strip()
        ]

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
