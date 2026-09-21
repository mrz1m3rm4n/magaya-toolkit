"""Tests for the `files` resource methods on the `Magaya` facade.

No network access: an httpx.MockTransport feeds canned SOAP responses so the
facade drives the real SOAP client and parser end to end.

Three wire-level facts are pinned here, each confirmed against a live install
and each a production failure if it regresses:

- `GetAllAttachments` sends `flags` BEFORE `type` — the reference's parameter
  order, and SOAP is positional.
- `GetAttachment` and `GetWebDocument` send NO `access_key`; including one is
  rejected with "SOAP Invalid Request".
- `documents()` reads the transaction with the `AttachDocsSummary` flag (0x40);
  without it Magaya lists no documents at all.
"""

from __future__ import annotations

import re
from base64 import b64encode
from collections.abc import Callable
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit import Magaya
from magaya_toolkit.domain.attachment import AttachmentRef, DocumentRef
from magaya_toolkit.domain.errors import SessionError
from magaya_toolkit.infrastructure.soap.magaya_client import MagayaSoapClient

_NS = 'xmlns:snp="urn:CSSoapService"'
_DATA_NS = "http://www.magaya.com/XMLSchema/V1"

_PAYLOAD = b"%PDF-1.3 fake body"
_PAYLOAD_B64 = b64encode(_PAYLOAD).decode("ascii")


def _soap(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        f"<soap:Body>{body}</soap:Body>"
        "</soap:Envelope>"
    )


def _start_session_response(access_key: int) -> str:
    return _soap(
        f"<snp:StartSessionResponse {_NS}>"
        "<snp:return>no_error</snp:return>"
        f"<snp:access_key>{access_key}</snp:access_key>"
        "</snp:StartSessionResponse>"
    )


def _end_session_response() -> str:
    return _soap(
        f"<snp:EndSessionResponse {_NS}>"
        "<snp:return>no_error</snp:return>"
        "</snp:EndSessionResponse>"
    )


def _all_attachments_response() -> str:
    doc = (
        f'<Attachments xmlns="{_DATA_NS}">'
        "<Attachment><Name>IN-F_78282</Name><Extension>xml</Extension>"
        "<IsImage>false</IsImage><IsInternal>false</IsInternal><Size>18</Size>"
        "<OwnerType>IN</OwnerType><OwnerGUID>inv-guid-1</OwnerGUID>"
        "<Identifier>144402385</Identifier></Attachment>"
        "</Attachments>"
    )
    return _soap(
        f"<snp:GetAllAttachmentsResponse {_NS}>"
        "<snp:return>no_error</snp:return>"
        f"<snp:attach_list_xml>{escape(doc)}</snp:attach_list_xml>"
        "</snp:GetAllAttachmentsResponse>"
    )


def _attachment_response() -> str:
    doc = (
        f'<Attachment xmlns="{_DATA_NS}">'
        "<Name>IN-F_78282</Name><Extension>xml</Extension>"
        f"<Size>{len(_PAYLOAD)}</Size><Data>{_PAYLOAD_B64}</Data>"
        "</Attachment>"
    )
    # Note: no <return> element — GetAttachment has no status retval.
    return _soap(
        f"<snp:GetAttachmentResponse {_NS}>"
        f"<snp:attach_xml>{escape(doc)}</snp:attach_xml>"
        "</snp:GetAttachmentResponse>"
    )


def _transaction_with_docs_response() -> str:
    doc = (
        f'<GroundShipment xmlns="{_DATA_NS}" GUID="sh-guid-1">'
        "<Number>TMSE2690826</Number>"
        "<Documents><Document><Name>BL</Name><Extension>dff</Extension>"
        "<IsMagayaDoc>true</IsMagayaDoc><IsOLEDoc>false</IsOLEDoc>"
        "<OwnerGUID>sh-guid-1</OwnerGUID><Identifier>144517945</Identifier>"
        "</Document></Documents>"
        "</GroundShipment>"
    )
    return _soap(
        f"<snp:GetTransactionResponse {_NS}>"
        "<snp:return>no_error</snp:return>"
        f"<snp:trans_xml>{escape(doc)}</snp:trans_xml>"
        "</snp:GetTransactionResponse>"
    )


def _web_document_response() -> str:
    return _soap(
        f"<snp:GetWebDocumentResponse {_NS}>"
        f"<snp:document>{_PAYLOAD_B64}</snp:document>"
        f"<snp:document_length>{len(_PAYLOAD_B64)}</snp:document_length>"
        "<snp:is_ole_doc>0</snp:is_ole_doc>"
        "</snp:GetWebDocumentResponse>"
    )


def _method(body: str) -> str | None:
    # "GetAttachment" is a substring of "GetAllAttachments"? No — but the ":"
    # guard keeps every pair apart regardless of order.
    for method in (
        "StartSession",
        "GetAllAttachments",
        "GetAttachment",
        "GetWebDocument",
        "GetTransaction",
        "EndSession",
    ):
        if f":{method}" in body:
            return method
    return None


def _facade(handler: Callable[[httpx.Request], httpx.Response]) -> Magaya:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = MagayaSoapClient(
        api_url="https://example.test/soap",
        username="user",
        password="pass",
        http_client=http_client,
    )
    return Magaya(client=client)


def _handler_for(
    bodies: list[str], responses: dict[str, str]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(555)
        elif method in responses:
            text = responses[method]
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    return handler


# -- attachments -----------------------------------------------------------


def test_attachments_sends_flags_before_type():
    """SOAP is positional: the reference's order is `access_key, flags, type, number`."""
    bodies: list[str] = []
    handler = _handler_for(bodies, {"GetAllAttachments": _all_attachments_response()})

    with _facade(handler) as magaya:
        refs = magaya.files.attachments("IN", "F-78282")

    assert len(refs) == 1
    assert refs[0].identifier == "144402385"
    assert refs[0].size == 18

    body = next(b for b in bodies if _method(b) == "GetAllAttachments")
    order = re.findall(r"<(access_key|flags|type|number) ", body)
    assert order == ["access_key", "flags", "type", "number"]


def test_attachment_sends_no_access_key_and_decodes_the_content():
    """`GetAttachment` rejects an access_key with "SOAP Invalid Request"."""
    bodies: list[str] = []
    handler = _handler_for(bodies, {"GetAttachment": _attachment_response()})
    ref = AttachmentRef(
        owner_type="IN", owner_guid="inv-guid-1", identifier="144402385"
    )

    with _facade(handler) as magaya:
        attachment = magaya.files.attachment(ref)

    assert attachment.data == _PAYLOAD
    assert attachment.size_matches is True

    body = next(b for b in bodies if _method(b) == "GetAttachment")
    assert "access_key" not in body
    assert '<attach_id xsi:type="xsd:int">144402385</attach_id>' in body


def test_fetching_an_incomplete_attachment_ref_is_refused():
    handler = _handler_for([], {})

    with _facade(handler) as magaya, pytest.raises(ValueError, match="owner_type"):
        magaya.files.attachment(AttachmentRef(name="orphan"))


# -- documents -------------------------------------------------------------


def test_documents_reads_the_transaction_with_the_attach_docs_summary_flag():
    """Without flag 0x40 Magaya lists no documents at all."""
    bodies: list[str] = []
    handler = _handler_for(bodies, {"GetTransaction": _transaction_with_docs_response()})

    with _facade(handler) as magaya:
        docs = magaya.files.documents("SH", "TMSE2690826")

    assert len(docs) == 1
    assert docs[0].identifier == "144517945"
    assert docs[0].extension == "dff"

    body = next(b for b in bodies if _method(b) == "GetTransaction")
    assert '<flags xsi:type="xsd:int">64</flags>' in body


def test_document_sends_no_access_key_and_reports_the_real_size():
    bodies: list[str] = []
    handler = _handler_for(bodies, {"GetWebDocument": _web_document_response()})
    ref = DocumentRef(owner_guid="sh-guid-1", identifier="144517945")

    with _facade(handler) as magaya:
        document = magaya.files.document(ref)

    assert document.data == _PAYLOAD
    assert document.size == len(_PAYLOAD)
    # What Magaya reports is the Base64 length, not the file size.
    assert document.encoded_length == len(_PAYLOAD_B64)
    assert document.size != document.encoded_length
    assert document.is_ole_doc is False

    body = next(b for b in bodies if _method(b) == "GetWebDocument")
    assert "access_key" not in body
    assert '<doc_id xsi:type="xsd:int">144517945</doc_id>' in body


def test_fetching_an_incomplete_document_ref_is_refused():
    handler = _handler_for([], {})

    with _facade(handler) as magaya, pytest.raises(ValueError, match="owner_guid"):
        magaya.files.document(DocumentRef(name="orphan"))


# -- session wiring --------------------------------------------------------


def test_listing_attachments_outside_a_with_block_raises():
    magaya = _facade(_handler_for([], {}))

    with pytest.raises(SessionError):
        magaya.files.attachments("IN", "F-78282")
