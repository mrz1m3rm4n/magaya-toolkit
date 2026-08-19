"""Tests for the `shipments.get` resource method on the `Magaya` facade.

No network access: an httpx.MockTransport feeds canned SOAP responses
(namespaced under urn:CSSoapService, trans_xml HTML-escaped) so the facade
drives the real SOAP client and parser end to end. The GetTransaction response
mirrors the real Magaya shape — the shipment element is the ROOT itself, not a
`<Shipments>` batch.
"""

from __future__ import annotations

from collections.abc import Callable
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit import Magaya
from magaya_toolkit.domain.errors import SessionError
from magaya_toolkit.infrastructure.soap.magaya_client import MagayaSoapClient

_NS = 'xmlns:snp="urn:CSSoapService"'
_DATA_NS = "http://www.magaya.com/XMLSchema/V1"


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
        f"<snp:return>no_error</snp:return>"
        f"<snp:access_key>{access_key}</snp:access_key>"
        "</snp:StartSessionResponse>"
    )


def _end_session_response() -> str:
    return _soap(
        f"<snp:EndSessionResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        "</snp:EndSessionResponse>"
    )


def _get_transaction_response(trans_xml: str) -> str:
    return _soap(
        f"<snp:GetTransactionResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetTransactionResponse>"
    )


def _accounting_transactions_response(trans_xml: str) -> str:
    return _soap(
        f"<snp:GetAccountingTransactionsResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetAccountingTransactionsResponse>"
    )


def _guid_items_doc() -> str:
    return (
        f'<GUIDItems xmlns="{_DATA_NS}">'
        "<GUIDItem><GUID>inv-guid-1</GUID><Type>Invoice</Type></GUIDItem>"
        "</GUIDItems>"
    )


def _shipment_doc() -> str:
    # Single-transaction shape: the <OceanShipment> element is the root.
    return (
        f'<OceanShipment xmlns="{_DATA_NS}" GUID="bed2a7ea-guid" Type="SH">'
        "<Number>TMSE2690826</Number>"
        "<Status>In Transit</Status>"
        "<ShipperName>Acme Corp</ShipperName>"
        "</OceanShipment>"
    )


def _method(body: str) -> str | None:
    for method in (
        "StartSession",
        "GetTransaction",
        "GetAccountingTransactions",
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


def test_get_reads_single_shipment_and_sends_type_sh_and_number():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetTransaction":
            text = _get_transaction_response(_shipment_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        shipment = magaya.shipments.get("TMSE2690826")

    assert shipment.number == "TMSE2690826"
    assert shipment.mode == "Ocean"
    assert shipment.guid == "bed2a7ea-guid"
    assert shipment.status == "In Transit"

    get_body = next(b for b in bodies if _method(b) == "GetTransaction")
    assert '<type xsi:type="xsd:string">SH</type>' in get_body
    assert '<number xsi:type="xsd:string">TMSE2690826</number>' in get_body


def test_accounting_transactions_reads_refs_and_sends_type_sh_and_number():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetAccountingTransactions":
            text = _accounting_transactions_response(_guid_items_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        refs = magaya.shipments.accounting_transactions("TMSE2690826")

    assert len(refs) == 1
    assert refs[0].guid == "inv-guid-1"
    assert refs[0].type == "Invoice"

    tx_body = next(b for b in bodies if _method(b) == "GetAccountingTransactions")
    assert '<type xsi:type="xsd:string">SH</type>' in tx_body
    assert '<number xsi:type="xsd:string">TMSE2690826</number>' in tx_body


def test_get_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.shipments.get("TMSE2690826")


def test_accounting_transactions_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.shipments.accounting_transactions("TMSE2690826")
