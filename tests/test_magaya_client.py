"""Unit tests for MagayaSoapClient.

No network access: an httpx.MockTransport feeds canned SOAP responses that
mirror the real ones (elements namespaced under urn:CSSoapService with an `snp`
prefix; trans_list_xml HTML-escaped) so the lxml local-name parsing and the
auto-unescaping are genuinely exercised.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.infrastructure.soap.magaya_client import MagayaSoapClient

_NS = 'xmlns:snp="urn:CSSoapService"'


def _soap(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        f"<soap:Body>{body}</soap:Body>"
        "</soap:Envelope>"
    )


def _start_session_response(access_key: int, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:StartSessionResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:access_key>{access_key}</snp:access_key>"
        "</snp:StartSessionResponse>"
    )


def _end_session_response(return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:EndSessionResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        "</snp:EndSessionResponse>"
    )


def _get_first_response(cookie: str, more_results: int) -> str:
    return _soap(
        f"<snp:GetFirstTransbyDateResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:cookie>{escape(cookie)}</snp:cookie>"
        f"<snp:more_results>{more_results}</snp:more_results>"
        "</snp:GetFirstTransbyDateResponse>"
    )


def _get_next_response(trans_list_xml: str, more_results: int, next_cookie: str = "cookie|next") -> str:
    # GetNext echoes an *updated* cookie (in/out cursor) that must be threaded
    # into the following call.
    return _soap(
        f"<snp:GetNextTransbyDateResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_list_xml>{escape(trans_list_xml)}</snp:trans_list_xml>"
        f"<snp:cookie>{escape(next_cookie)}</snp:cookie>"
        f"<snp:more_results>{more_results}</snp:more_results>"
        "</snp:GetNextTransbyDateResponse>"
    )


def _get_transaction_response(trans_xml: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:GetTransactionResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetTransactionResponse>"
    )


def _query_log_response(trans_list_xml: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:QueryLogResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:trans_list_xml>{escape(trans_list_xml)}</snp:trans_list_xml>"
        "</snp:QueryLogResponse>"
    )


def _get_entity_transactions_response(acctrans_list_xml: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:GetEntityTransactionsResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:acctrans_list_xml>{escape(acctrans_list_xml)}</snp:acctrans_list_xml>"
        "</snp:GetEntityTransactionsResponse>"
    )


def _get_accounting_transactions_response(trans_xml: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:GetAccountingTransactionsResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetAccountingTransactionsResponse>"
    )


def _get_related_transactions_response(trans_xml: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:GetRelatedTransactionsResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>"
        "</snp:GetRelatedTransactionsResponse>"
    )


def _guid_items_doc() -> str:
    # A minimal <GUIDItems> doc: children may carry only GUID + Type (no
    # LogType/LogDate) — the related-transaction reads return exactly this shape.
    return (
        '<GUIDItems xmlns="http://www.magaya.com/XMLSchema/V1">'
        "<GUIDItem><GUID>g-1</GUID><Type>Invoice</Type></GUIDItem>"
        "<GUIDItem><GUID>g-2</GUID><Type>Invoice</Type></GUIDItem>"
        "</GUIDItems>"
    )


def _fault_response(faultstring: str) -> str:
    return _soap(
        "<soap:Fault>"
        "<faultcode>soap:Server</faultcode>"
        f"<faultstring>{escape(faultstring)}</faultstring>"
        "</soap:Fault>"
    )


def _exists_transaction_response(exist_trans: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:ExistsTransactionResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:exist_trans>{exist_trans}</snp:exist_trans>"
        "</snp:ExistsTransactionResponse>"
    )


def _transaction_status_response(status: str, return_code: str = "no_error") -> str:
    return _soap(
        f"<snp:GetTransactionStatusResponse {_NS}>"
        f"<snp:return>{return_code}</snp:return>"
        f"<snp:trans_status>{escape(status)}</snp:trans_status>"
        "</snp:GetTransactionStatusResponse>"
    )


def _client(handler) -> MagayaSoapClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return MagayaSoapClient(
        api_url="https://example.test/soap",
        username="user",
        password="pass",
        http_client=http_client,
    )


def _single_response(body: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"Content-Type": "text/xml"})

    return handler


def test_start_session_parses_access_key():
    client = _client(_single_response(_start_session_response(123456)))
    assert client.start_session() == 123456


def test_return_code_error_raises_api_error():
    client = _client(_single_response(_start_session_response(0, return_code="access_denied")))
    with pytest.raises(ApiError) as exc:
        client.start_session()
    assert "access_denied" in str(exc.value)


def test_soap_fault_raises_api_error():
    client = _client(_single_response(_fault_response("SOAP Invalid Request")))
    with pytest.raises(ApiError) as exc:
        client.start_session()
    assert "SOAP Invalid Request" in str(exc.value)


def test_get_next_unescapes_inner_xml_and_reports_no_more_results():
    inner = '<Shipments xmlns="http://www.magaya.com/XMLSchema/V1"><Shipment><Number>1</Number></Shipment></Shipments>'
    client = _client(_single_response(_get_next_response(inner, more_results=0)))
    trans_list_xml, next_cookie, more_results = client.get_next_trans_by_date("cookie|value")
    assert trans_list_xml == inner
    assert next_cookie == "cookie|next"
    assert more_results is False


def _sent_cookie(body: str) -> str | None:
    match = re.search(r"<cookie[^>]*>(.*?)</cookie>", body, re.DOTALL)
    return match.group(1) if match else None


def test_read_transactions_by_date_iterates_and_ends_session():
    requests: list[str] = []
    sent_cookies: list[str] = []

    responses = iter(
        [
            _start_session_response(999),
            _get_first_response("cookie|abc", more_results=1),
            _get_next_response("<chunk>1</chunk>", more_results=1, next_cookie="cookie|p2"),
            _get_next_response("<chunk>2</chunk>", more_results=0, next_cookie="cookie|p3"),
            _end_session_response(),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        # Record which method was invoked by its element local-name.
        for method in (
            "StartSession",
            "GetFirstTransbyDate",
            "GetNextTransbyDate",
            "EndSession",
        ):
            if f":{method}" in body:
                requests.append(method)
                if method == "GetNextTransbyDate":
                    sent_cookies.append(_sent_cookie(body))
                break
        return httpx.Response(200, text=next(responses), headers={"Content-Type": "text/xml"})

    client = _client(handler)
    chunks = list(
        client.read_transactions_by_date(
            trans_type="SH",
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
    )

    assert chunks == ["<chunk>1</chunk>", "<chunk>2</chunk>"]
    assert requests == [
        "StartSession",
        "GetFirstTransbyDate",
        "GetNextTransbyDate",
        "GetNextTransbyDate",
        "EndSession",
    ]
    # Regression: the second GetNext must use the cookie RETURNED by the first
    # GetNext (threaded), not the original GetFirst cookie. Reusing the same
    # cookie would loop over the same page forever.
    assert sent_cookies == ["cookie|abc", "cookie|p2"]


def test_get_transaction_sends_documented_params_and_unescapes_response():
    captured: dict[str, str] = {}
    # Opaque payload: this test only proves the client passes the raw trans_xml
    # through (unescaped). The real single-transaction XML shape is validated
    # live before a parser is built against it.
    inner = '<Shipment xmlns="http://www.magaya.com/XMLSchema/V1"><Number>BL-1</Number></Shipment>'

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            text=_get_transaction_response(inner),
            headers={"Content-Type": "text/xml"},
        )

    client = _client(handler)
    result = client.get_transaction(access_key=42, trans_type="SH", number="BL-1")

    body = captured["body"]
    assert ":GetTransaction" in body
    # Parameters and their wire types must match the Magaya API reference.
    assert '<access_key xsi:type="xsd:int">42</access_key>' in body
    assert '<type xsi:type="xsd:string">SH</type>' in body
    assert '<flags xsi:type="xsd:int">0</flags>' in body
    assert '<number xsi:type="xsd:string">BL-1</number>' in body
    assert result == inner


def test_get_transaction_not_found_raises_api_error():
    # The live API returns `transaction_not_found` (one "c"); the wiki doc's
    # `transaccion_not_found` is a typo. Validated against real Magaya.
    client = _client(
        _single_response(
            _get_transaction_response("", return_code="transaction_not_found")
        )
    )
    with pytest.raises(ApiError) as exc:
        client.get_transaction(access_key=1, trans_type="SH", number="does-not-exist")
    assert "transaction_not_found" in str(exc.value)


def test_exists_transaction_true_when_found():
    client = _client(_single_response(_exists_transaction_response("1")))
    assert client.exists_transaction(1, "SH", "TMSE2690826") is True


def test_exists_transaction_false_on_not_found_without_raising():
    # `transaction_not_found` + exist_trans=0 means "does not exist", NOT an
    # error — validated live. The method returns False rather than raising.
    client = _client(
        _single_response(
            _exists_transaction_response("0", return_code="transaction_not_found")
        )
    )
    assert client.exists_transaction(1, "SH", "NOPE") is False


def test_exists_transaction_raises_on_other_error():
    client = _client(
        _single_response(_exists_transaction_response("0", return_code="access_denied"))
    )
    with pytest.raises(ApiError):
        client.exists_transaction(1, "SH", "x")


def test_get_transaction_status_returns_status_string():
    client = _client(_single_response(_transaction_status_response("Delivered")))
    assert client.get_transaction_status(1, "SH", "TMSE2690826") == "Delivered"


def test_query_log_sends_documented_params_and_unescapes_response():
    captured: dict[str, str] = {}
    # Opaque payload: this test only proves the client passes the raw
    # trans_list_xml through (unescaped). The <GUIDItems> shape is validated by
    # the parser tests.
    inner = (
        '<GUIDItems xmlns="http://www.magaya.com/XMLSchema/V1">'
        "<GUIDItem><GUID>g-1</GUID><Type>Invoice</Type></GUIDItem>"
        "</GUIDItems>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            text=_query_log_response(inner),
            headers={"Content-Type": "text/xml"},
        )

    client = _client(handler)
    result = client.query_log(
        access_key=42,
        start_date="2026-07-01T00:00:00",
        end_date="2026-07-31T23:59:59",
        log_entry_type=1,
        trans_type="IN",
    )

    body = captured["body"]
    assert ":QueryLog" in body
    # Parameters and their wire types must match the Magaya API reference.
    assert '<access_key xsi:type="xsd:int">42</access_key>' in body
    assert '<start_date xsi:type="xsd:string">2026-07-01T00:00:00</start_date>' in body
    assert '<end_date xsi:type="xsd:string">2026-07-31T23:59:59</end_date>' in body
    assert '<log_entry_type xsi:type="xsd:int">1</log_entry_type>' in body
    assert '<trans_type xsi:type="xsd:string">IN</trans_type>' in body
    assert '<flags xsi:type="xsd:int">0</flags>' in body
    assert result == inner


def test_get_entity_transactions_sends_documented_params_and_unescapes_response():
    captured: dict[str, str] = {}
    inner = _guid_items_doc()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            text=_get_entity_transactions_response(inner),
            headers={"Content-Type": "text/xml"},
        )

    client = _client(handler)
    result = client.get_entity_transactions(
        access_key=42,
        entity_uuid="ent-guid-1",
        start_date="2026-07-01",
        end_date="2026-07-31",
    )

    body = captured["body"]
    assert ":GetEntityTransactions" in body
    # Parameters, order and their wire types must match the Magaya API reference.
    assert '<access_key xsi:type="xsd:int">42</access_key>' in body
    assert '<entity_uuid xsi:type="xsd:string">ent-guid-1</entity_uuid>' in body
    assert '<flags xsi:type="xsd:int">0</flags>' in body
    assert '<start_date xsi:type="xsd:string">2026-07-01</start_date>' in body
    assert '<end_date xsi:type="xsd:string">2026-07-31</end_date>' in body
    assert result == inner


def test_get_accounting_transactions_sends_documented_params_and_unescapes_response():
    captured: dict[str, str] = {}
    inner = _guid_items_doc()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            text=_get_accounting_transactions_response(inner),
            headers={"Content-Type": "text/xml"},
        )

    client = _client(handler)
    result = client.get_accounting_transactions(
        access_key=42, trans_type="SH", number="TMSE2690826"
    )

    body = captured["body"]
    assert ":GetAccountingTransactions" in body
    assert '<access_key xsi:type="xsd:int">42</access_key>' in body
    assert '<type xsi:type="xsd:string">SH</type>' in body
    assert '<flags xsi:type="xsd:int">0</flags>' in body
    assert '<number xsi:type="xsd:string">TMSE2690826</number>' in body
    assert result == inner


def test_get_related_transactions_sends_documented_params_and_unescapes_response():
    captured: dict[str, str] = {}
    inner = _guid_items_doc()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            text=_get_related_transactions_response(inner),
            headers={"Content-Type": "text/xml"},
        )

    client = _client(handler)
    result = client.get_related_transactions(
        access_key=42, trans_type="IN", number="F-78282"
    )

    body = captured["body"]
    assert ":GetRelatedTransactions" in body
    assert '<access_key xsi:type="xsd:int">42</access_key>' in body
    assert '<type xsi:type="xsd:string">IN</type>' in body
    assert '<flags xsi:type="xsd:int">0</flags>' in body
    assert '<number xsi:type="xsd:string">F-78282</number>' in body
    assert result == inner


def test_get_first_sends_backwards_order_as_int():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            text=_get_first_response("cookie|x", more_results=0),
            headers={"Content-Type": "text/xml"},
        )

    client = _client(handler)
    client.get_first_trans_by_date(
        access_key=1,
        trans_type="SH",
        start_date="2026-01-01",
        end_date="2026-01-31",
        record_quantity=5,
        backwards_order=True,
    )
    body = captured["body"]
    assert '<backwards_order xsi:type="xsd:int">1</backwards_order>' in body
    assert "xsd:boolean" not in body
