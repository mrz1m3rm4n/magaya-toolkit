"""lxml-based implementation of the `XmlValidator` port.

Two levels of checking:
1. Well-formedness — always. The document must parse as XML.
2. Schema validation — optional. If an XSD path is given, the document is
   validated against it (this is how we will enforce the Magaya Transactions
   format once we have the schema in `schemas/`).
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from magaya_toolkit.domain.errors import XmlValidationError


class LxmlValidator:
    def __init__(self, xsd_path: Path | None = None) -> None:
        self._schema: etree.XMLSchema | None = None
        if xsd_path is not None:
            schema_doc = etree.parse(str(xsd_path))
            self._schema = etree.XMLSchema(schema_doc)

    def validate(self, xml: bytes) -> None:
        try:
            doc = etree.fromstring(xml)
        except etree.XMLSyntaxError as exc:
            raise XmlValidationError(
                "The document is not well-formed XML.",
                problems=[str(exc)],
            ) from exc

        if self._schema is None:
            return

        if not self._schema.validate(doc):
            problems = [str(e) for e in self._schema.error_log]
            raise XmlValidationError(
                "The document does not match the expected Magaya schema.",
                problems=problems,
            )
