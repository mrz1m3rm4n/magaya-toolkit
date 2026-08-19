"""Tests for the `invoices` resource methods on the `Magaya` facade.

No network access: an httpx.MockTransport feeds canned SOAP responses
(namespaced under urn:CSSoapService, inner XML HTML-escaped) so the facade
drives the real SOAP client and parsers end to end. `query` reads a QueryLog
<GUIDItems> document; `get` reads a single <Invoice> (the element is the ROOT
itself, mirroring the real Magaya GetTransaction shape).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
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


def _query_log_response(trans_list_xml: str) -> str:
    return _soap(
        f"<snp:QueryLogResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_list_xml>{escape(trans_list_xml)}</snp:trans_list_xml>"
        "</snp:QueryLogResponse>"
    )


def _get_transaction_response(trans_xml: str) -> str:
    return _soap(
        f"<snp:GetTransactionResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetTransactionResponse>"
    )


def _related_transactions_response(trans_xml: str) -> str:
    return _soap(
        f"<snp:GetRelatedTransactionsResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetRelatedTransactionsResponse>"
    )


def _related_guid_items_doc() -> str:
    return (
        f'<GUIDItems xmlns="{_DATA_NS}">'
        "<GUIDItem><GUID>sh-guid-1</GUID><Type>OceanShipment</Type></GUIDItem>"
        "</GUIDItems>"
    )


def _guid_items_doc() -> str:
    return (
        f'<GUIDItems xmlns="{_DATA_NS}">'
        "<GUIDItem><GUID>inv-guid-1</GUID><Type>Invoice</Type>"
        "<LogType>Creation</LogType>"
        "<LogDate>2026-07-01T10:10:17-06:00</LogDate></GUIDItem>"
        "</GUIDItems>"
    )


def _invoice_doc() -> str:
    return (
        f'<Invoice xmlns="{_DATA_NS}" GUID="inv-guid-1" Type="IN">'
        "<Number>F-78282</Number>"
        "<Status>Open</Status>"
        '<TotalAmount Currency="MXN">1500.00</TotalAmount>'
        '<Currency Code="MXN"><Name>Mexican Peso</Name></Currency>'
        "<Entity><Name>Acme Client Corp</Name></Entity>"
        "</Invoice>"
    )


def _exists_response(exist_trans: str) -> str:
    return _soap(
        f"<snp:ExistsTransactionResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:exist_trans>{exist_trans}</snp:exist_trans>"
        "</snp:ExistsTransactionResponse>"
    )


def _status_response(status: str) -> str:
    return _soap(
        f"<snp:GetTransactionStatusResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_status>{escape(status)}</snp:trans_status>"
        "</snp:GetTransactionStatusResponse>"
    )


def _method(body: str) -> str | None:
    # `GetTransactionStatus` must be checked BEFORE `GetTransaction` — the latter
    # is a substring of the former, so the general one would shadow it.
    for method in (
        "StartSession",
        "QueryLog",
        "GetTransactionStatus",
        "GetTransaction",
        "GetRelatedTransactions",
        "ExistsTransaction",
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


def test_query_reads_invoice_refs_and_sends_trans_type_in():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "QueryLog":
            text = _query_log_response(_guid_items_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        refs = magaya.invoices.query("2026-07-01T00:00:00", "2026-07-31T23:59:59")

    assert len(refs) == 1
    assert refs[0].guid == "inv-guid-1"
    assert refs[0].type == "Invoice"
    assert refs[0].log_type == "Creation"

    query_body = next(b for b in bodies if _method(b) == "QueryLog")
    assert '<trans_type xsi:type="xsd:string">IN</trans_type>' in query_body


def test_get_reads_single_invoice_and_sends_type_in_and_number():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetTransaction":
            text = _get_transaction_response(_invoice_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        invoice = magaya.invoices.get("F-78282")

    assert invoice.number == "F-78282"
    assert invoice.guid == "inv-guid-1"
    assert invoice.type_code == "IN"
    assert invoice.status == "Open"
    assert invoice.total_amount == Decimal("1500.00")
    assert invoice.currency == "MXN"
    assert invoice.entity_name == "Acme Client Corp"

    get_body = next(b for b in bodies if _method(b) == "GetTransaction")
    assert '<type xsi:type="xsd:string">IN</type>' in get_body
    assert '<number xsi:type="xsd:string">F-78282</number>' in get_body


def test_related_reads_refs_and_sends_type_in_and_number():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetRelatedTransactions":
            text = _related_transactions_response(_related_guid_items_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        refs = magaya.invoices.related("F-78282")

    assert len(refs) == 1
    assert refs[0].guid == "sh-guid-1"
    assert refs[0].type == "OceanShipment"

    related_body = next(b for b in bodies if _method(b) == "GetRelatedTransactions")
    assert '<type xsi:type="xsd:string">IN</type>' in related_body
    assert '<number xsi:type="xsd:string">F-78282</number>' in related_body


def test_query_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.invoices.query("2026-07-01T00:00:00", "2026-07-31T23:59:59")


def test_get_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.invoices.get("F-78282")


def test_related_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.invoices.related("F-78282")


def test_exists_returns_bool_and_sends_type_in_and_number():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "ExistsTransaction":
            text = _exists_response("1")
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        assert magaya.invoices.exists("F-78282") is True

    body = next(b for b in bodies if _method(b) == "ExistsTransaction")
    assert '<type xsi:type="xsd:string">IN</type>' in body
    assert '<number xsi:type="xsd:string">F-78282</number>' in body


def test_status_returns_string_and_sends_type_in():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetTransactionStatus":
            text = _status_response("Open")
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        assert magaya.invoices.status("F-78282") == "Open"

    body = next(b for b in bodies if _method(b) == "GetTransactionStatus")
    assert '<type xsi:type="xsd:string">IN</type>' in body
