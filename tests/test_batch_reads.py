"""Tests for the batch and server-side-filtered reads. No network access.

Three things are pinned here, all of them learned the hard way against a live
install:

- The transport must parse responses whose escaped payload exceeds lxml's
  default 10 MB text-node ceiling. One day of invoices really is ~30 MB, and
  before the fix it died with "Text node too long, try XML_PARSE_HUGE".
- `GetFirstTransbyDateJS` sends `backwards_order` as `xsd:int`, not
  `xsd:boolean`, whatever the API reference's `BOOL` says.
- `QueryLogJS` sends `trans_type`, which the reference's signature block omits
  (it is a copy of `QueryLog`'s) but its own sample envelope includes.

The `*JS` methods are not JSON variants — they filter server-side with a
JavaScript predicate defined inside Magaya.
"""

from __future__ import annotations

from collections.abc import Callable
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit import Magaya
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.infrastructure.soap.magaya_client import MagayaSoapClient
from magaya_toolkit.resources import _js_parameters

_NS = 'xmlns:snp="urn:CSSoapService"'
_DATA_NS = "http://www.magaya.com/XMLSchema/V1"

# lxml refuses text nodes over 10,000,000 characters unless huge_tree is on.
_LXML_TEXT_NODE_LIMIT = 10_000_000


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


def _list_response(method: str, payload: str, code: str = "no_error") -> str:
    return _soap(
        f"<snp:{method}Response {_NS}>"
        f"<snp:return>{code}</snp:return>"
        f"<snp:trans_list_xml>{escape(payload)}</snp:trans_list_xml>"
        f"</snp:{method}Response>"
    )


def _first_js_response(cookie: str, more: str) -> str:
    return _soap(
        f"<snp:GetFirstTransbyDateJSResponse {_NS}>"
        "<snp:return>no_error</snp:return>"
        f"<snp:cookie>{cookie}</snp:cookie>"
        f"<snp:more_results>{more}</snp:more_results>"
        "</snp:GetFirstTransbyDateJSResponse>"
    )


def _invoices_doc(count: int = 1, filler: str = "") -> str:
    body = "".join(
        f'<Invoice GUID="inv-{i}" Type="IN"><Number>F-{i}</Number>'
        f"<Status>Open</Status><Notes>{filler}</Notes></Invoice>"
        for i in range(count)
    )
    return f'<Invoices xmlns="{_DATA_NS}">{body}</Invoices>'


def _method(body: str) -> str | None:
    for method in (
        "StartSession",
        "GetTransRangeByDateJS",
        "GetTransRangeByDate",
        "GetTransactionsByBillingClient",
        "GetFirstTransbyDateJS",
        "QueryLogJS",
        "QueryLog",
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
            text = _start_session_response(111)
        elif method in responses:
            text = responses[method]
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    return handler


# -- the transport ceiling -------------------------------------------------


def test_the_transport_parses_a_payload_over_lxmls_text_node_limit():
    """A real day of invoices is ~30 MB escaped into one text node."""
    filler = "A" * (_LXML_TEXT_NODE_LIMIT + 500_000)
    payload = _invoices_doc(1, filler)
    assert len(escape(payload)) > _LXML_TEXT_NODE_LIMIT

    handler = _handler_for([], {"GetTransRangeByDate": _list_response("GetTransRangeByDate", payload)})

    with _facade(handler) as magaya:
        invoices = magaya.invoices.range("2026-07-01", "2026-07-02")

    assert len(invoices) == 1
    assert invoices[0].number == "F-0"


# -- batch reads -----------------------------------------------------------


def test_range_reads_a_whole_invoice_batch():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {"GetTransRangeByDate": _list_response("GetTransRangeByDate", _invoices_doc(3))},
    )

    with _facade(handler) as magaya:
        invoices = magaya.invoices.range("2026-07-01", "2026-07-02")

    assert [i.number for i in invoices] == ["F-0", "F-1", "F-2"]

    body = next(b for b in bodies if _method(b) == "GetTransRangeByDate")
    assert '<type xsi:type="xsd:string">IN</type>' in body
    assert '<start_date xsi:type="xsd:string">2026-07-01</start_date>' in body


def test_for_billing_client_sends_the_client_guid_and_type():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetTransactionsByBillingClient": _list_response(
                "GetTransactionsByBillingClient", _invoices_doc(1)
            )
        },
    )

    with _facade(handler) as magaya:
        invoices = magaya.invoices.for_billing_client(
            "client-guid-1", "2026-07-01", "2026-07-02"
        )

    assert len(invoices) == 1

    body = next(b for b in bodies if _method(b) == "GetTransactionsByBillingClient")
    assert '<customer_uuid xsi:type="xsd:string">client-guid-1</customer_uuid>' in body
    assert '<type xsi:type="xsd:string">IN</type>' in body


def test_an_install_with_no_billing_client_gets_an_empty_list():
    empty = f'<Invoices xmlns="{_DATA_NS}"/>'
    handler = _handler_for(
        [],
        {
            "GetTransactionsByBillingClient": _list_response(
                "GetTransactionsByBillingClient", empty
            )
        },
    )

    with _facade(handler) as magaya:
        assert magaya.invoices.for_billing_client("x", "2026-07-01", "2026-07-02") == []


# -- the JavaScript filter -------------------------------------------------


def test_js_parameters_builds_the_positional_parameters_document():
    assert _js_parameters(None) == ""
    assert _js_parameters([]) == ""
    assert (
        _js_parameters(["OnHand", "DIV 1"])
        == "<Parameters><Parameter>OnHand</Parameter><Parameter>DIV 1</Parameter></Parameters>"
    )


def test_js_parameters_escapes_values():
    assert _js_parameters(["a & b"]) == "<Parameters><Parameter>a &amp; b</Parameter></Parameters>"


def test_a_js_function_routes_the_range_read_to_the_filtered_variant():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetTransRangeByDateJS": _list_response(
                "GetTransRangeByDateJS", _invoices_doc(1)
            )
        },
    )

    with _facade(handler) as magaya:
        magaya.invoices.range(
            "2026-07-01", "2026-07-02", js_function="byStatus", js_params=["Open"]
        )

    assert not any(_method(b) == "GetTransRangeByDate" for b in bodies)
    body = next(b for b in bodies if _method(b) == "GetTransRangeByDateJS")
    assert '<function xsi:type="xsd:string">byStatus</function>' in body
    assert "&lt;Parameters&gt;&lt;Parameter&gt;Open&lt;/Parameter&gt;" in body


def test_without_a_js_function_the_plain_variant_is_used():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {"GetTransRangeByDate": _list_response("GetTransRangeByDate", _invoices_doc(1))},
    )

    with _facade(handler) as magaya:
        magaya.invoices.range("2026-07-01", "2026-07-02")

    assert any(_method(b) == "GetTransRangeByDate" for b in bodies)
    assert not any(_method(b) == "GetTransRangeByDateJS" for b in bodies)


def test_an_unknown_js_function_surfaces_as_an_api_error():
    """Magaya reports it as `invalid_operation`, verified against a live install."""
    handler = _handler_for(
        [],
        {
            "GetTransRangeByDateJS": _list_response(
                "GetTransRangeByDateJS", "", "invalid_operation"
            )
        },
    )

    with _facade(handler) as magaya, pytest.raises(ApiError, match="invalid_operation"):
        magaya.invoices.range("2026-07-01", "2026-07-02", js_function="noSuchFunction")


def test_the_filtered_pagination_sends_backwards_order_as_an_int():
    """The reference declares BOOL; `xsd:boolean` is rejected by the live API."""
    bodies: list[str] = []
    handler = _handler_for(bodies, {"GetFirstTransbyDateJS": _first_js_response("", "0")})

    with _facade(handler) as magaya:
        magaya.shipments.list(
            "2026-07-01", "2026-07-02", js_function="byStatus", js_params=["Loaded"]
        )

    body = next(b for b in bodies if _method(b) == "GetFirstTransbyDateJS")
    assert '<backwards_order xsi:type="xsd:int">0</backwards_order>' in body
    assert "xsd:boolean" not in body


def test_query_log_js_sends_trans_type_the_reference_signature_omits():
    bodies: list[str] = []
    guid_items = f'<GUIDItems xmlns="{_DATA_NS}"/>'
    handler = _handler_for(bodies, {"QueryLogJS": _list_response("QueryLogJS", guid_items)})

    with _facade(handler) as magaya:
        magaya.invoices.query(
            "2026-07-01T00:00:00",
            "2026-07-02T00:00:00",
            log_entry_type=-1,
            js_function="byDivision",
            js_params=["DIV 1"],
        )

    body = next(b for b in bodies if _method(b) == "QueryLogJS")
    assert '<trans_type xsi:type="xsd:string">IN</trans_type>' in body
    assert '<log_entry_type xsi:type="xsd:int">-1</log_entry_type>' in body
    assert '<log_flags xsi:type="xsd:int">0</log_flags>' in body
    assert '<xml_flags xsi:type="xsd:int">0</xml_flags>' in body
