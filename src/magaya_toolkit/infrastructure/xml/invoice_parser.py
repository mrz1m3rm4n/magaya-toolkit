"""lxml-based parser for a single Magaya invoice `GetTransaction` response.

Parses the Magaya `<Invoice>` document into an `Invoice` domain read model.

Two invariants worth spelling out:

1. Namespace. The document is namespaced under
   ``http://www.magaya.com/XMLSchema/V1`` (singular "XMLSchema"). We read
   elements by local-name so a missing/mismatched namespace prefix never hides
   a field.
2. Direct children only. An `<Invoice>` element carries its own fields as
   *direct* children, but the same tag names (e.g. ``Number``) also appear deep
   inside nested entities such as ``<CreatedBy>``. We iterate only direct
   children so a nested ``<Number>`` can never be mistaken for the invoice's own
   number.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.domain.invoice import Invoice

# Expected root local-name for a single-transaction invoice read.
_ROOT_LOCAL_NAME = "Invoice"


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlInvoiceParser:
    """Parse a single Magaya `<Invoice>` XML into an `Invoice` read model."""

    def parse_one(self, trans_xml: str | bytes) -> Invoice:
        """Parse a single-transaction `GetTransaction` response into an `Invoice`.

        `GetTransaction(type="IN", ...)` returns the invoice element itself as
        the root (`<Invoice>`), so we hand the root straight to `_to_invoice`.
        Raises `XmlValidationError` on malformed XML or when the root is not an
        `<Invoice>` element.
        """
        raw = trans_xml.encode("utf-8") if isinstance(trans_xml, str) else trans_xml
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                "The transaction document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc

        if _local_name(root) != _ROOT_LOCAL_NAME:
            raise XmlValidationError(
                f"Expected an <{_ROOT_LOCAL_NAME}> root, got <{_local_name(root)}>.",
            )
        return self._to_invoice(root)

    # -- element -> domain -------------------------------------------------

    def _to_invoice(self, element: etree._Element) -> Invoice:
        # Read ONLY direct children into a local-name -> element map. The last
        # occurrence wins, which is fine for the flat direct-child fields.
        children: dict[str, etree._Element] = {}
        for child in element:
            if isinstance(child.tag, str):
                children[_local_name(child)] = child

        return Invoice(
            guid=element.get("GUID"),
            number=self._text(children, "Number") or "",
            type_code=element.get("Type"),
            status=self._text(children, "Status"),
            created_on=self._datetime(children, "CreatedOn"),
            due_date=self._datetime(children, "DueDate"),
            entity_name=self._nested_text(children, "Entity", "Name"),
            issued_by_name=self._nested_text(children, "IssuedBy", "Name"),
            total_amount=self._decimal(children, "TotalAmount"),
            home_currency=self._attr(children, "HomeCurrency", "Code"),
            currency=self._attr(children, "Currency", "Code"),
            total_amount_in_currency=self._decimal(children, "TotalAmountInCurrency"),
            exchange_rate=self._decimal(children, "ExchangeRate"),
            tax_amount=self._decimal(children, "TaxAmount"),
            tax_amount_in_currency=self._decimal(children, "TaxAmountInCurrency"),
            is_prepaid=self._bool(children, "IsPrepaid"),
            is_periodic=self._bool(children, "IsPeriodic"),
            is_printed=self._bool(children, "IsPrinted"),
            is_fiscal_printed=self._bool(children, "IsFiscalPrinted"),
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
        """Read an attribute off a direct child element.

        Magaya carries the currency code as an attribute (e.g.
        `<Currency Code="MXN">`, `<TotalAmount Currency="MXN">`), not as text.
        """
        node = children.get(name)
        if node is None:
            return None
        value = node.get(attr)
        if value is None:
            return None
        value = value.strip()
        return value or None

    @classmethod
    def _nested_text(
        cls, children: dict[str, etree._Element], name: str, grandchild: str
    ) -> str | None:
        """Read the text of a direct `<grandchild>` inside a direct `<name>` child.

        E.g. `Entity/Name -> entity_name`. Reads only the direct `<Name>` child
        of the direct `<Entity>` child so a deeper `<Name>` never wins.
        """
        node = children.get(name)
        if node is None:
            return None
        for child in node:
            if isinstance(child.tag, str) and _local_name(child) == grandchild:
                if child.text is None:
                    return None
                text = child.text.strip()
                return text or None
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
    def _decimal(cls, children: dict[str, etree._Element], name: str) -> Decimal | None:
        text = cls._text(children, name)
        if text is None:
            return None
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return None
