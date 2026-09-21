"""Unit tests for LxmlAttachmentParser. No network access.

The documents mirror shapes captured from a live Magaya install. Two of the
assertions pin facts the Magaya API reference gets wrong:

- an `<Attachment>` really carries `<IsInternal>` and `<Size>`, which the
  reference's example omits;
- `GetWebDocument`'s `document_length` is the length of the Base64 STRING, not
  the size of the file, whatever the reference says.
"""

from __future__ import annotations

from base64 import b64encode

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.attachment_parser import LxmlAttachmentParser

_NS = "http://www.magaya.com/XMLSchema/V1"

_PAYLOAD = b'\xef\xbb\xbf<?xml version="1.0"?>\r\n<cfdi:Comprobante/>'
_PAYLOAD_B64 = b64encode(_PAYLOAD).decode("ascii")

_ATTACHMENTS = f"""<?xml version="1.0" encoding="utf-8"?>
<Attachments xmlns="{_NS}">
  <Attachment>
    <Name>IN-F_78282</Name>
    <Extension>xml</Extension>
    <IsImage>false</IsImage>
    <IsInternal>false</IsInternal>
    <Size>5485</Size>
    <OwnerType>IN</OwnerType>
    <OwnerGUID>ec60f1ff-c153-4049-b41d-122a71863684</OwnerGUID>
    <Identifier>144402385</Identifier>
  </Attachment>
  <Attachment>
    <Name>Broken Pallet</Name>
    <Extension>jpg</Extension>
    <IsImage>true</IsImage>
    <OwnerType>WH</OwnerType>
    <OwnerGUID>93881c49-ebdc-4ed8-8c30-10e7abf3d3c0</OwnerGUID>
    <Identifier>343028</Identifier>
  </Attachment>
</Attachments>"""

_ONE_ATTACHMENT = f"""<?xml version="1.0" encoding="utf-8"?>
<Attachment xmlns="{_NS}">
  <Name>IN-F_78282</Name>
  <Extension>xml</Extension>
  <IsImage>false</IsImage>
  <IsInternal>false</IsInternal>
  <Size>{len(_PAYLOAD)}</Size>
  <Data>{_PAYLOAD_B64}</Data>
</Attachment>"""

# A transaction read with the AttachDocsSummary flag: documents live inside it,
# under a root whose name varies with the shipment kind.
_TRANSACTION_WITH_DOCS = f"""<?xml version="1.0" encoding="utf-8"?>
<GroundShipment xmlns="{_NS}" GUID="sh-guid-1">
  <Number>TMSE2690826</Number>
  <Documents>
    <Document>
      <Name>NOT FCL LOGISTICA WEPORT</Name>
      <Extension>dff</Extension>
      <IsMagayaDoc>true</IsMagayaDoc>
      <IsOLEDoc>false</IsOLEDoc>
      <OwnerGUID>d1a0f46b-f71c-47ea-8f7c-edc2e8c2825f</OwnerGUID>
      <Identifier>144517945</Identifier>
    </Document>
  </Documents>
</GroundShipment>"""


@pytest.fixture
def parser() -> LxmlAttachmentParser:
    return LxmlAttachmentParser()


# -- listing ---------------------------------------------------------------


def test_parses_every_listed_attachment_with_its_fetch_keys(
    parser: LxmlAttachmentParser,
) -> None:
    invoice_xml, pallet_photo = parser.parse_list(_ATTACHMENTS)

    # These three are exactly what GetAttachment needs.
    assert invoice_xml.owner_type == "IN"
    assert invoice_xml.owner_guid == "ec60f1ff-c153-4049-b41d-122a71863684"
    assert invoice_xml.identifier == "144402385"

    # IsInternal and Size are absent from the API reference's example.
    assert invoice_xml.is_internal is False
    assert invoice_xml.size == 5485
    assert invoice_xml.is_image is False

    assert pallet_photo.is_image is True
    assert pallet_photo.size is None
    assert pallet_photo.is_internal is None


def test_a_transaction_with_no_attachments_is_an_empty_list(
    parser: LxmlAttachmentParser,
) -> None:
    assert parser.parse_list(f'<Attachments xmlns="{_NS}"/>') == []


# -- content ---------------------------------------------------------------


def test_decodes_the_base64_content_into_bytes(parser: LxmlAttachmentParser) -> None:
    attachment = parser.parse_one(_ONE_ATTACHMENT)

    assert attachment.data == _PAYLOAD
    assert attachment.size == len(_PAYLOAD)
    assert attachment.size_matches is True
    assert attachment.suggested_filename() == "IN-F_78282.xml"


def test_a_size_that_disagrees_with_the_content_is_reported(
    parser: LxmlAttachmentParser,
) -> None:
    """A truncated transfer should be visible before the file is written."""
    doc = _ONE_ATTACHMENT.replace(f"<Size>{len(_PAYLOAD)}</Size>", "<Size>99999</Size>")

    attachment = parser.parse_one(doc)

    assert attachment.size_matches is False


def test_undecodable_content_yields_none_instead_of_raising(
    parser: LxmlAttachmentParser,
) -> None:
    """A corrupt blob must not make the rest of the record unreadable."""
    doc = _ONE_ATTACHMENT.replace(_PAYLOAD_B64, "!!! not base64 !!!")

    attachment = parser.parse_one(doc)

    assert attachment.data is None
    assert attachment.name == "IN-F_78282"
    assert attachment.size_matches is None


def test_decodes_base64_that_magaya_line_wraps(parser: LxmlAttachmentParser) -> None:
    """Magaya wraps Base64 MIME-style; strict decoding rejects the newlines.

    Caught against a live install, not by a hand-written fixture: every sample
    written by hand is unwrapped, so only real data exercises this.
    """
    wrapped = "\n".join(_PAYLOAD_B64[i : i + 8] for i in range(0, len(_PAYLOAD_B64), 8))
    assert "\n" in wrapped
    doc = _ONE_ATTACHMENT.replace(_PAYLOAD_B64, wrapped)

    attachment = parser.parse_one(doc)

    assert attachment.data == _PAYLOAD
    assert attachment.size_matches is True


def test_web_document_decodes_line_wrapped_base64_too(
    parser: LxmlAttachmentParser,
) -> None:
    wrapped = "\n".join(_PAYLOAD_B64[i : i + 8] for i in range(0, len(_PAYLOAD_B64), 8))

    document = parser.build_web_document(wrapped, str(len(wrapped)), "0")

    assert document.data == _PAYLOAD


def test_an_attachment_without_data_still_parses(parser: LxmlAttachmentParser) -> None:
    doc = f'<Attachment xmlns="{_NS}"><Name>Empty</Name></Attachment>'

    attachment = parser.parse_one(doc)

    assert attachment.data is None
    assert attachment.suggested_filename() == "Empty"


# -- documents -------------------------------------------------------------


def test_finds_documents_inside_a_transaction_of_any_root(
    parser: LxmlAttachmentParser,
) -> None:
    (doc,) = parser.parse_documents(_TRANSACTION_WITH_DOCS)

    assert doc.name == "NOT FCL LOGISTICA WEPORT"
    assert doc.extension == "dff"
    assert doc.is_magaya_doc is True
    assert doc.is_ole_doc is False
    assert doc.owner_guid == "d1a0f46b-f71c-47ea-8f7c-edc2e8c2825f"
    assert doc.identifier == "144517945"


def test_a_transaction_read_without_the_flag_lists_no_documents(
    parser: LxmlAttachmentParser,
) -> None:
    plain = f'<GroundShipment xmlns="{_NS}"><Number>X</Number></GroundShipment>'

    assert parser.parse_documents(plain) == []


def test_web_document_length_is_the_base64_length_not_the_file_size(
    parser: LxmlAttachmentParser,
) -> None:
    """The API reference calls `document_length` a byte size. It is not."""
    encoded = b64encode(b"%PDF-1.3 fake pdf body").decode("ascii")

    document = parser.build_web_document(encoded, str(len(encoded)), "0")

    assert document.data == b"%PDF-1.3 fake pdf body"
    assert document.encoded_length == len(encoded)
    assert document.size == 22
    # Base64 expands by 4/3, so the two never agree on a non-empty document.
    assert document.encoded_length != document.size
    assert document.is_ole_doc is False


def test_web_document_handles_an_absent_document(parser: LxmlAttachmentParser) -> None:
    document = parser.build_web_document("", "", "")

    assert document.data is None
    assert document.size is None
    assert document.encoded_length is None
    assert document.is_ole_doc is None


# -- failure modes ---------------------------------------------------------


def test_rejects_a_list_document_with_the_wrong_root(
    parser: LxmlAttachmentParser,
) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse_list(_ONE_ATTACHMENT)


def test_rejects_malformed_xml(parser: LxmlAttachmentParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse_list("<Attachments><Attachment>")
