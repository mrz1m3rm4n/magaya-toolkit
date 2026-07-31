"""Tests for the `Magaya` SDK facade. No network access.

An httpx.MockTransport feeds canned SOAP responses (namespaced under
urn:CSSoapService, trans_list_xml HTML-escaped) so the facade drives the real
SOAP client and parser end to end. These tests prove the facade manages exactly
one session across multiple resource calls, closes it on exit even when a
resource raises, and refuses to work before the session is open.
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
_SHIPMENTS_NS = "http://www.magaya.com/XMLSchema/V1"


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


def _get_first_response(cookie: str, more_results: int) -> str:
    return _soap(
        f"<snp:GetFirstTransbyDateResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:cookie>{escape(cookie)}</snp:cookie>"
        f"<snp:more_results>{more_results}</snp:more_results>"
        "</snp:GetFirstTransbyDateResponse>"
    )


def _get_next_response(
    trans_list_xml: str, more_results: int, next_cookie: str = "cookie|next"
) -> str:
    return _soap(
        f"<snp:GetNextTransbyDateResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:trans_list_xml>{escape(trans_list_xml)}</snp:trans_list_xml>"
        f"<snp:cookie>{escape(next_cookie)}</snp:cookie>"
        f"<snp:more_results>{more_results}</snp:more_results>"
        "</snp:GetNextTransbyDateResponse>"
    )


def _shipment(guid: str, number: str) -> str:
    return f'<OceanShipment GUID="{guid}" Type="SH"><Number>{number}</Number></OceanShipment>'


def _doc(*inner: str) -> str:
    return f'<Shipments xmlns="{_SHIPMENTS_NS}">{"".join(inner)}</Shipments>'


def _method(body: str) -> str | None:
    for method in ("StartSession", "GetFirstTransbyDate", "GetNextTransbyDate", "EndSession"):
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


def test_shipments_list_returns_shipments():
    responses = iter(
        [
            _start_session_response(999),
            _get_first_response("cookie|abc", more_results=1),
            _get_next_response(_doc(_shipment("a", "SH-1"), _shipment("b", "SH-2")), more_results=0),
            _end_session_response(),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=next(responses), headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        shipments = magaya.shipments.list("2025-01-01", "2025-01-31")

    assert [s.number for s in shipments] == ["SH-1", "SH-2"]
    assert [s.guid for s in shipments] == ["a", "b"]


def test_two_resource_calls_reuse_a_single_session():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        method = _method(body)
        calls.append(method)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetFirstTransbyDate":
            text = _get_first_response("cookie|abc", more_results=1)
        elif method == "GetNextTransbyDate":
            text = _get_next_response(_doc(_shipment("a", "SH-1")), more_results=0)
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        first = magaya.shipments.list("2025-01-01", "2025-01-31")
        second = magaya.shipments.list("2025-02-01", "2025-02-28")

    assert [s.number for s in first] == ["SH-1"]
    assert [s.number for s in second] == ["SH-1"]
    # The session is reused, not reopened per call: exactly one StartSession and
    # exactly one EndSession across both resource calls.
    assert calls.count("StartSession") == 1
    assert calls.count("EndSession") == 1


def test_using_a_resource_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.shipments.list("2025-01-01", "2025-01-31")
    # Accessing the access_key directly raises the same error.
    with pytest.raises(SessionError):
        _ = magaya.access_key


def test_end_session_is_sent_even_when_a_resource_raises():
    calls: list[str] = []

    class _Boom(Exception):
        pass

    def handler(request: httpx.Request) -> httpx.Response:
        method = _method(request.content.decode("utf-8"))
        calls.append(method)
        if method == "StartSession":
            text = _start_session_response(999)
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with pytest.raises(_Boom), _facade(handler):
        raise _Boom()

    # EndSession must still be sent on `with` exit despite the in-block failure.
    assert calls == ["StartSession", "EndSession"]
