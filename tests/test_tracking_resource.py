"""Tests for the `tracking` resource on the `Magaya` facade. No network access.

`GetSecureTrackingTransaction` is the odd one out: it does not use the API
session at all. It authenticates with a LiveTrack CLIENT's own name and
password and returns only what that client may see. Two facts are pinned, both
confirmed against a live install:

- it sends NO `access_key`; including one is rejected with "SOAP Invalid
  Request";
- wrong credentials come back as the `access_denied` return code.

Its successful body could not be observed — no LiveTrack client credentials
were available — so the fixtures use the `GetTransaction` shape the API
reference says it mirrors, and which the rest of the suite verifies for real.
"""

from __future__ import annotations

from collections.abc import Callable
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit import Magaya
from magaya_toolkit.domain.errors import ApiError
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


def _tracking_response(trans_xml: str, code: str = "no_error") -> str:
    inner = f"<snp:trans_xml>{escape(trans_xml)}</snp:trans_xml>" if trans_xml else ""
    return _soap(
        f"<snp:GetSecureTrackingTransactionResponse {_NS}>"
        f"<snp:return>{code}</snp:return>{inner}"
        "</snp:GetSecureTrackingTransactionResponse>"
    )


def _shipment_doc() -> str:
    return (
        f'<GroundShipment xmlns="{_DATA_NS}" GUID="sh-guid-1">'
        "<Number>TMSE2690826</Number><Status>InTransit</Status>"
        "</GroundShipment>"
    )


def _invoice_doc() -> str:
    return (
        f'<Invoice xmlns="{_DATA_NS}" GUID="inv-guid-1" Type="IN">'
        "<Number>F-78282</Number><Status>Open</Status>"
        "</Invoice>"
    )


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> MagayaSoapClient:
    transport = httpx.MockTransport(handler)
    return MagayaSoapClient(
        api_url="https://example.test/soap",
        username="user",
        password="pass",
        http_client=httpx.Client(transport=transport),
    )


def _facade_and_bodies(
    response: str,
) -> tuple[Magaya, list[str]]:
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode("utf-8"))
        return httpx.Response(
            200, text=response, headers={"Content-Type": "text/xml"}
        )

    return Magaya(client=_client(handler)), bodies


# -- the wire contract -----------------------------------------------------


def test_a_tracking_read_sends_no_access_key():
    """Magaya rejects an access_key here with "SOAP Invalid Request"."""
    magaya, bodies = _facade_and_bodies(_tracking_response(_shipment_doc()))

    magaya.tracking.shipment("acme-client", "s3cret", "sh-guid-1")

    (body,) = bodies
    assert "access_key" not in body


def test_it_sends_the_client_credentials_and_the_transaction_type():
    magaya, bodies = _facade_and_bodies(_tracking_response(_shipment_doc()))

    magaya.tracking.shipment("acme-client", "s3cret", "sh-guid-1")

    (body,) = bodies
    assert '<user xsi:type="xsd:string">acme-client</user>' in body
    assert '<pass xsi:type="xsd:string">s3cret</pass>' in body
    assert '<app xsi:type="xsd:string">SH</app>' in body
    assert '<number xsi:type="xsd:string">sh-guid-1</number>' in body


def test_the_invoice_variant_sends_the_invoice_type():
    magaya, bodies = _facade_and_bodies(_tracking_response(_invoice_doc()))

    invoice = magaya.tracking.invoice("acme-client", "s3cret", "inv-guid-1")

    assert invoice.number == "F-78282"
    (body,) = bodies
    assert '<app xsi:type="xsd:string">IN</app>' in body


# -- behaviour -------------------------------------------------------------


def test_it_parses_the_transaction_the_client_is_allowed_to_see():
    magaya, _ = _facade_and_bodies(_tracking_response(_shipment_doc()))

    shipment = magaya.tracking.shipment("acme-client", "s3cret", "sh-guid-1")

    assert shipment.number == "TMSE2690826"
    assert shipment.status == "InTransit"


def test_wrong_credentials_raise_api_error():
    """Verified against a live install: Magaya answers `access_denied`."""
    magaya, _ = _facade_and_bodies(_tracking_response("", "access_denied"))

    with pytest.raises(ApiError, match="access_denied"):
        magaya.tracking.shipment("nobody", "wrong", "sh-guid-1")


def test_it_works_without_an_open_session():
    """There is no access_key to acquire, so no `with` block is needed."""
    magaya, bodies = _facade_and_bodies(_tracking_response(_shipment_doc()))

    # Note: no `with`, no open() — every other resource would raise SessionError.
    shipment = magaya.tracking.shipment("acme-client", "s3cret", "sh-guid-1")

    assert shipment.number == "TMSE2690826"
    # Exactly one call: no StartSession was needed either.
    assert len(bodies) == 1
    assert ":StartSession" not in bodies[0]
