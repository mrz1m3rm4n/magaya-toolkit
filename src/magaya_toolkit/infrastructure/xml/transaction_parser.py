"""lxml-based parser for `QueryLog` `<GUIDItems>` documents.

Parses the Magaya `<GUIDItems>` document into `TransactionRef` domain read
models. Each direct `<GUIDItem>` child becomes one reference.

Namespace: the document is namespaced under
``http://www.magaya.com/XMLSchema/V1`` (singular "XMLSchema"). We read elements
by local-name so a missing/mismatched namespace prefix never hides a field.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

from datetime import datetime

from lxml import etree

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.domain.transaction import TransactionRef

# Expected root local-name for a Magaya QueryLog result.
_ROOT_LOCAL_NAME = "GUIDItems"


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlGuidItemsParser:
    """Parse Magaya `<GUIDItems>` XML into `TransactionRef` read models."""

    def parse(self, trans_list_xml: str | bytes) -> list[TransactionRef]:
        raw = trans_list_xml.encode("utf-8") if isinstance(trans_list_xml, str) else trans_list_xml
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                "The QueryLog document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc

        if _local_name(root) != _ROOT_LOCAL_NAME:
            raise XmlValidationError(
                f"Expected a <{_ROOT_LOCAL_NAME}> root, got <{_local_name(root)}>.",
            )

        refs: list[TransactionRef] = []
        # Direct children of <GUIDItems> are the individual <GUIDItem> elements.
        for element in root:
            # Skip comments/processing instructions.
            if not isinstance(element.tag, str):
                continue
            refs.append(self._to_ref(element))
        return refs

    # -- element -> domain -------------------------------------------------

    def _to_ref(self, element: etree._Element) -> TransactionRef:
        # Read ONLY direct children into a local-name -> element map.
        children: dict[str, etree._Element] = {}
        for child in element:
            if isinstance(child.tag, str):
                children[_local_name(child)] = child

        return TransactionRef(
            guid=self._text(children, "GUID") or "",
            type=self._text(children, "Type") or "",
            log_type=self._text(children, "LogType"),
            log_date=self._datetime(children, "LogDate"),
        )

    # -- field readers -----------------------------------------------------

    @staticmethod
    def _text(children: dict[str, etree._Element], name: str) -> str | None:
        node = children.get(name)
        if node is None or node.text is None:
            return None
        text = node.text.strip()
        return text or None

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
