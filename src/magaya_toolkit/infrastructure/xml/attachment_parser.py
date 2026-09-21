"""lxml-based parser for Magaya attachment and document documents.

Handles the three shapes involved in getting a file off a transaction:

- `<Attachments>` — the list returned by `GetAllAttachments`.
- `<Attachment>` — one file with its Base64 `<Data>`, from `GetAttachment`.
- `<Documents>` — Magaya's own documents, which live INSIDE a transaction read
  with the `AttachDocsSummary` flag rather than in a document of their own.

Base64 is decoded here, at the infrastructure boundary, so the domain models
carry real bytes. A `<Data>` element that is absent or not valid Base64 yields
`data=None` rather than raising: a corrupt blob should not make an otherwise
readable attachment record unusable.

Same namespace rule as the other parsers: elements are read by local-name under
``http://www.magaya.com/XMLSchema/V1``.

Read-only: nothing here mutates or emits Magaya data.
"""

from __future__ import annotations

import binascii
import re
from base64 import b64decode

from lxml import etree

from magaya_toolkit.domain.attachment import (
    Attachment,
    AttachmentRef,
    DocumentRef,
    WebDocument,
)
from magaya_toolkit.domain.errors import XmlValidationError

_ATTACHMENTS_ROOT = "Attachments"
_ATTACHMENT_ROOT = "Attachment"

_WHITESPACE = re.compile(r"\s+")


def _decode_base64(text: str | None) -> bytes | None:
    """Decode Magaya's Base64, or None if it is absent or genuinely corrupt.

    Magaya line-wraps Base64 MIME-style (a newline every 76 characters), which
    strict decoding rejects outright. Whitespace is stripped first so wrapping
    is tolerated, and validation is kept on so a truly malformed blob is still
    reported as None rather than silently truncated.
    """
    if text is None:
        return None
    compact = _WHITESPACE.sub("", text)
    if not compact:
        return None
    try:
        return b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return None


def _local_name(element: etree._Element) -> str:
    """Return the tag local-name (namespace stripped)."""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag if isinstance(tag, str) else ""


class LxmlAttachmentParser:
    """Parse Magaya attachment/document XML into read models."""

    # -- documents ---------------------------------------------------------

    def parse_list(self, attach_list_xml: str | bytes) -> list[AttachmentRef]:
        """Parse an `<Attachments>` document into `AttachmentRef` pointers.

        A transaction with no attachments yields an empty `<Attachments>`, and
        this returns [].
        """
        root = self._root(attach_list_xml, _ATTACHMENTS_ROOT)
        return [
            self._to_ref(element) for element in root if isinstance(element.tag, str)
        ]

    def parse_one(self, attach_xml: str | bytes) -> Attachment:
        """Parse a single `<Attachment>` document, decoding its `<Data>`."""
        root = self._root(attach_xml, _ATTACHMENT_ROOT)
        children = self._children(root)
        return Attachment(
            name=self._text(children, "Name"),
            extension=self._text(children, "Extension"),
            is_image=self._bool(children, "IsImage"),
            is_internal=self._bool(children, "IsInternal"),
            size=self._int(children, "Size"),
            data=self._b64(children, "Data"),
        )

    def parse_documents(self, trans_xml: str | bytes) -> list[DocumentRef]:
        """Collect the `<Document>` entries from a transaction's XML.

        Magaya lists documents inside the transaction, not in a document of
        their own, so this takes the transaction XML as read with the
        `AttachDocsSummary` flag. A transaction without the flag (or without
        documents) yields [].
        """
        raw = trans_xml.encode("utf-8") if isinstance(trans_xml, str) else trans_xml
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                "The transaction document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc
        nodes = root.xpath("//*[local-name()='Documents']/*[local-name()='Document']")
        return [self._to_document_ref(node) for node in nodes]

    def build_web_document(
        self, document_b64: str, document_length: str, is_ole_doc: str
    ) -> WebDocument:
        """Assemble a `WebDocument` from the three fields `GetWebDocument` returns.

        `GetWebDocument` answers with loose out-parameters instead of an XML
        document, so there is nothing to parse — but the Base64 decoding and the
        0/1 flag belong on this side of the boundary all the same.
        """
        data = _decode_base64(document_b64)
        length: int | None = None
        try:
            length = int(document_length)
        except (TypeError, ValueError):
            length = None
        flag = (is_ole_doc or "").strip()
        return WebDocument(
            data=data,
            encoded_length=length,
            is_ole_doc=flag in ("1", "true", "True") if flag else None,
        )

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

    def _to_ref(self, element: etree._Element) -> AttachmentRef:
        children = self._children(element)
        return AttachmentRef(
            name=self._text(children, "Name"),
            extension=self._text(children, "Extension"),
            is_image=self._bool(children, "IsImage"),
            is_internal=self._bool(children, "IsInternal"),
            size=self._int(children, "Size"),
            owner_type=self._text(children, "OwnerType"),
            owner_guid=self._text(children, "OwnerGUID"),
            identifier=self._text(children, "Identifier"),
        )

    def _to_document_ref(self, element: etree._Element) -> DocumentRef:
        children = self._children(element)
        return DocumentRef(
            name=self._text(children, "Name"),
            extension=self._text(children, "Extension"),
            is_magaya_doc=self._bool(children, "IsMagayaDoc"),
            is_ole_doc=self._bool(children, "IsOLEDoc"),
            owner_guid=self._text(children, "OwnerGUID"),
            identifier=self._text(children, "Identifier"),
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
    def _b64(cls, children: dict[str, etree._Element], name: str) -> bytes | None:
        """Decode a Base64 element; None if absent or not decodable."""
        node = children.get(name)
        if node is None:
            return None
        return _decode_base64(node.text)
