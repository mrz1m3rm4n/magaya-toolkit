"""Tests for the `rates` resource methods on the `Magaya` facade.

No network access: an httpx.MockTransport feeds canned SOAP responses so the
facade drives the real SOAP client and parser end to end.

The wire-level assertions matter more than usual here. `include_standard` is
declared `int` by the Magaya API reference but described as "TRUE if…", and
sending it as `xsd:boolean` is rejected with "SOAP Invalid Request" — the same
trap as `backwards_order` on `GetFirstTransbyDate`. A regression there is a
production failure no parser test would catch.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit import Magaya
from magaya_toolkit.domain.errors import ApiError, SessionError
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


def _rates_response(method: str, rate_list_xml: str, code: str = "no_error") -> str:
    return _soap(
        f"<snp:{method}Response {_NS}>"
        f"<snp:return>{code}</snp:return>"
        f"<snp:rate_list_xml>{escape(rate_list_xml)}</snp:rate_list_xml>"
        f"</snp:{method}Response>"
    )


def _rates_doc(root: str, rate_type: str) -> str:
    return (
        f'<{root} xmlns="{_DATA_NS}">'
        '<Rate GUID="rate-guid-1">'
        f"<Type>{rate_type}</Type>"
        '<Carrier GUID="carrier-guid-1"><Type>Carrier</Type>'
        "<Name>MAERSK</Name></Carrier>"
        '<OriginCountry Code="MX">MEXICO</OriginCountry>'
        "<ApplyBy>Package</ApplyBy>"
        "<PackageRates><PackageRate>"
        "<Package><Code>CNT</Code></Package>"
        '<Price Currency="MXN">50.00</Price>'
        "</PackageRate></PackageRates>"
        "</Rate>"
        f"</{root}>"
    )


def _method(body: str) -> str | None:
    for method in (
        "StartSession",
        "GetStandardRates",
        "GetClientRates",
        "GetCarrierRates",
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
            text = _start_session_response(777)
        elif method in responses:
            text = responses[method]
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    return handler


# -- the three reads -------------------------------------------------------


def test_standard_reads_the_standard_rates_document():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetStandardRates": _rates_response(
                "GetStandardRates", _rates_doc("StandardRates", "Standard")
            )
        },
    )

    with _facade(handler) as magaya:
        rates = magaya.rates.standard()

    assert len(rates) == 1
    assert rates[0].type == "Standard"
    assert rates[0].prices == [Decimal("50.00")]

    body = next(b for b in bodies if _method(b) == "GetStandardRates")
    assert '<access_key xsi:type="xsd:int">777</access_key>' in body


def test_for_carrier_reads_the_carrier_rates_document_and_sends_carrier_uuid():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetCarrierRates": _rates_response(
                "GetCarrierRates", _rates_doc("CarrierRates", "Carrier")
            )
        },
    )

    with _facade(handler) as magaya:
        rates = magaya.rates.for_carrier("carrier-guid-1")

    assert rates[0].type == "Carrier"
    assert rates[0].carrier is not None
    assert rates[0].carrier.name == "MAERSK"

    body = next(b for b in bodies if _method(b) == "GetCarrierRates")
    assert '<carrier_uuid xsi:type="xsd:string">carrier-guid-1</carrier_uuid>' in body


# -- the include_standard wire type ---------------------------------------


@pytest.mark.parametrize(
    ("include_standard", "expected"),
    [(True, "1"), (False, "0")],
)
def test_include_standard_goes_on_the_wire_as_xsd_int(
    include_standard: bool, expected: str
):
    """xsd:boolean is rejected by Magaya with "SOAP Invalid Request"."""
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetClientRates": _rates_response(
                "GetClientRates", _rates_doc("ClientRates", "Client")
            )
        },
    )

    with _facade(handler) as magaya:
        magaya.rates.for_client("client-guid-1", include_standard=include_standard)

    body = next(b for b in bodies if _method(b) == "GetClientRates")
    assert (
        f'<include_standard xsi:type="xsd:int">{expected}</include_standard>' in body
    )
    assert "xsd:boolean" not in body


# -- the lane filter -------------------------------------------------------


def test_lane_filter_is_sent_on_every_read():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetStandardRates": _rates_response(
                "GetStandardRates", _rates_doc("StandardRates", "Standard")
            )
        },
    )

    with _facade(handler) as magaya:
        magaya.rates.standard(org_port="MXZLO", dest_port="USLAX", method="Ocean")

    body = next(b for b in bodies if _method(b) == "GetStandardRates")
    assert '<org_port xsi:type="xsd:string">MXZLO</org_port>' in body
    assert '<dest_port xsi:type="xsd:string">USLAX</dest_port>' in body
    assert '<method xsi:type="xsd:string">Ocean</method>' in body


def test_omitted_lane_filter_is_sent_blank_meaning_no_filter():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetStandardRates": _rates_response(
                "GetStandardRates", _rates_doc("StandardRates", "Standard")
            )
        },
    )

    with _facade(handler) as magaya:
        magaya.rates.standard()

    body = next(b for b in bodies if _method(b) == "GetStandardRates")
    assert '<org_port xsi:type="xsd:string"></org_port>' in body
    assert '<method xsi:type="xsd:string"></method>' in body


def test_an_unknown_port_surfaces_as_an_api_error():
    """Magaya reports it as the `invalid_operation` return code, not a fault."""
    handler = _handler_for(
        [],
        {"GetStandardRates": _rates_response("GetStandardRates", "", "invalid_operation")},
    )

    with _facade(handler) as magaya, pytest.raises(ApiError, match="invalid_operation"):
        magaya.rates.standard(org_port="BADPORT")


# -- session wiring --------------------------------------------------------


def test_rate_read_outside_a_with_block_raises():
    magaya = _facade(_handler_for([], {}))

    with pytest.raises(SessionError):
        magaya.rates.standard()
