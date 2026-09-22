"""Tests for the `inventory` resource methods on the `Magaya` facade.

No network access: an httpx.MockTransport feeds canned SOAP responses so the
facade drives the real SOAP client and parser end to end.

The wire-level assertion worth having: `GetItemDefinitionsByCustomer` names its
parameter `customer_uuid`, while its sibling `GetClientChargeDefinitions` names
the same idea `client_uuid` and rejects `customer_uuid`. Magaya really is
inconsistent here — both were checked against a live install — so each is
pinned where it belongs.
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


def _response(method: str, field: str, payload: str, code: str = "no_error") -> str:
    inner = f"<snp:{field}>{escape(payload)}</snp:{field}>" if payload else ""
    return _soap(
        f"<snp:{method}Response {_NS}>"
        f"<snp:return>{code}</snp:return>{inner}"
        f"</snp:{method}Response>"
    )


def _definitions_doc() -> str:
    return (
        f'<ItemDefinitions xmlns="{_DATA_NS}">'
        '<ItemDefinition GUID="def-guid-1" Type="IV">'
        "<PartNumber>10001-01-11</PartNumber>"
        "<Description>TERGAL PREMIER</Description>"
        "<Pieces>41</Pieces>"
        '<UnitaryValue Currency="MXN">125.50</UnitaryValue>'
        "</ItemDefinition>"
        "</ItemDefinitions>"
    )


def _items_doc() -> str:
    return (
        f'<Items xmlns="{_DATA_NS}">'
        '<Item GUID="item-guid-1" Type="IV">'
        "<Status>OnHand</Status><Pieces>1</Pieces>"
        "<SerialNumber>305773</SerialNumber>"
        '<Location Code="G101"><Description>RACK G</Description></Location>'
        "</Item>"
        "</Items>"
    )


def _one_item_doc() -> str:
    return (
        f'<Item xmlns="{_DATA_NS}" GUID="veh-1" Type="IV">'
        "<SerialNumber>1HGCM82633A004352</SerialNumber>"
        "</Item>"
    )


def _method(body: str) -> str | None:
    for method in (
        "StartSession",
        "GetItemDefinitionsByCustomer",
        "GetInventoryItemsByItemDefinition",
        "GetItemFromVIN",
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
            text = _start_session_response(321)
        elif method in responses:
            text = responses[method]
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    return handler


# -- definitions -----------------------------------------------------------


def test_definitions_sends_customer_uuid_not_client_uuid():
    """The sibling charge method wants `client_uuid`; this one rejects it."""
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetItemDefinitionsByCustomer": _response(
                "GetItemDefinitionsByCustomer", "def_list_xml", _definitions_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        definitions = magaya.inventory.definitions("client-guid-1")

    assert len(definitions) == 1
    assert definitions[0].pieces == 41
    assert definitions[0].unitary_value is not None
    assert definitions[0].unitary_value.value == Decimal("125.50")

    body = next(b for b in bodies if _method(b) == "GetItemDefinitionsByCustomer")
    assert '<customer_uuid xsi:type="xsd:string">client-guid-1</customer_uuid>' in body
    assert "client_uuid" not in body


def test_definitions_with_no_customer_sends_an_empty_uuid():
    """An empty GUID is how Magaya returns the customer-less definitions."""
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetItemDefinitionsByCustomer": _response(
                "GetItemDefinitionsByCustomer", "def_list_xml", _definitions_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        magaya.inventory.definitions()

    body = next(b for b in bodies if _method(b) == "GetItemDefinitionsByCustomer")
    assert '<customer_uuid xsi:type="xsd:string"></customer_uuid>' in body


# -- items -----------------------------------------------------------------


def test_items_sends_the_definition_guid_as_uuid():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetInventoryItemsByItemDefinition": _response(
                "GetInventoryItemsByItemDefinition", "item_list_xml", _items_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        items = magaya.inventory.items("def-guid-1")

    assert len(items) == 1
    assert items[0].serial_number == "305773"
    assert items[0].location is not None
    assert items[0].location.code == "G101"

    body = next(b for b in bodies if _method(b) == "GetInventoryItemsByItemDefinition")
    assert '<uuid xsi:type="xsd:string">def-guid-1</uuid>' in body


def test_a_definition_with_no_stock_returns_an_empty_list():
    empty = f'<Items xmlns="{_DATA_NS}"/>'
    handler = _handler_for(
        [],
        {
            "GetInventoryItemsByItemDefinition": _response(
                "GetInventoryItemsByItemDefinition", "item_list_xml", empty
            )
        },
    )

    with _facade(handler) as magaya:
        assert magaya.inventory.items("def-guid-2") == []


# -- the VIN lookup --------------------------------------------------------


def test_an_unknown_vin_raises_api_error():
    """Verified against a live install: Magaya answers `transaction_not_found`."""
    handler = _handler_for(
        [],
        {"GetItemFromVIN": _response("GetItemFromVIN", "", "", "transaction_not_found")},
    )

    with _facade(handler) as magaya, pytest.raises(ApiError, match="transaction_not_found"):
        magaya.inventory.item_from_vin("1HGCM82633A004352")


def test_a_found_vin_parses_into_an_inventory_item():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {"GetItemFromVIN": _response("GetItemFromVIN", "item_xml", _one_item_doc())},
    )

    with _facade(handler) as magaya:
        item = magaya.inventory.item_from_vin("1HGCM82633A004352")

    assert item.guid == "veh-1"
    assert item.serial_number == "1HGCM82633A004352"

    body = next(b for b in bodies if _method(b) == "GetItemFromVIN")
    assert '<vin xsi:type="xsd:string">1HGCM82633A004352</vin>' in body


# -- session wiring --------------------------------------------------------


def test_inventory_read_outside_a_with_block_raises():
    magaya = _facade(_handler_for([], {}))

    with pytest.raises(SessionError):
        magaya.inventory.definitions()
