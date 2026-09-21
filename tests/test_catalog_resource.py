"""Tests for the `catalog` resource methods on the `Magaya` facade.

No network access: an httpx.MockTransport feeds canned SOAP responses so the
facade drives the real SOAP client and parser end to end.

Beyond the happy path, these tests pin down three wire-level facts that the
Magaya API reference gets wrong or easy to misread, each confirmed against a
live install:

- `GetWorkingPorts` takes NO `access_key`; sending one is rejected.
- `GetClientChargeDefinitions` names its parameter `client_uuid`, not the
  documented `customer_uuid`.
- `GetChargeDefinitions` returns `service_list_xml`, not `charge_list_xml`.

A regression on any of those is a "SOAP Invalid Request" against production
that no parser test would catch.
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
        "<snp:return>no_error</snp:return>"
        "</snp:EndSessionResponse>"
    )


def _catalog_response(method: str, out_field: str, payload: str) -> str:
    return _soap(
        f"<snp:{method}Response {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:{out_field}>{escape(payload)}</snp:{out_field}>"
        f"</snp:{method}Response>"
    )


def _currencies_doc() -> str:
    return (
        f'<Currencies xmlns="{_DATA_NS}">'
        '<Currency Code="EUR"><Name>Euro</Name>'
        "<ExchangeRate>0.05069297294009104254</ExchangeRate>"
        "<DecimalPlaces>2</DecimalPlaces>"
        "<IsHomeCurrency>false</IsHomeCurrency></Currency>"
        "</Currencies>"
    )


def _event_definitions_doc() -> str:
    return (
        f'<EventDefinitions xmlns="{_DATA_NS}">'
        "<EventDefinition><Name>Recolectado</Name>"
        "<IncludeInTracking>true</IncludeInTracking></EventDefinition>"
        "</EventDefinitions>"
    )


def _account_definitions_doc() -> str:
    return (
        f'<AccountDefinitions xmlns="{_DATA_NS}">'
        "<AccountDefinition><Type>AccountReceivable</Type>"
        "<Name>Cuentas por cobrar (MXN)</Name>"
        '<Currency Code="MXN"><Name>Mexican Peso</Name></Currency>'
        "</AccountDefinition>"
        "</AccountDefinitions>"
    )


def _charge_definitions_doc() -> str:
    return (
        f'<ChargeDefinitions xmlns="{_DATA_NS}">'
        "<ChargeDefinition><Type>Other</Type>"
        "<Description>Ganancia Compartida</Description>"
        "<Code>AGT-INC</Code>"
        '<Amount Currency="MXN">0.00</Amount>'
        '<Currency Code="MXN"><Name>Mexican Peso</Name></Currency>'
        "</ChargeDefinition>"
        "</ChargeDefinitions>"
    )


def _ports_doc() -> str:
    return (
        f'<Ports xmlns="{_DATA_NS}">'
        '<Port Code="DWC"><Country Code="AE">UNITED ARAB EMIRATES</Country>'
        "<Method>Air</Method><Method>Ocean</Method>"
        "<Name>MAKTOUM</Name></Port>"
        "</Ports>"
    )


def _method(body: str) -> str | None:
    # The leading ":" keeps "GetChargeDefinitions" from matching inside
    # "GetClientChargeDefinitions"; the client method is still listed first so
    # the guard is not the only thing keeping them apart.
    for method in (
        "StartSession",
        "GetActiveCurrencies",
        "GetEventDefinitions",
        "GetAccountDefinitions",
        "GetClientChargeDefinitions",
        "GetChargeDefinitions",
        "GetWorkingPorts",
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
            text = _start_session_response(999)
        elif method in responses:
            text = responses[method]
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    return handler


# -- the five session-scoped catalog reads ---------------------------------


def test_currencies_reads_the_currency_list_and_keeps_rate_precision():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetActiveCurrencies": _catalog_response(
                "GetActiveCurrencies", "currency_list_xml", _currencies_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        currencies = magaya.catalog.currencies()

    assert len(currencies) == 1
    assert currencies[0].code == "EUR"
    assert currencies[0].exchange_rate == Decimal("0.05069297294009104254")

    body = next(b for b in bodies if _method(b) == "GetActiveCurrencies")
    assert '<access_key xsi:type="xsd:int">999</access_key>' in body


def test_events_reads_the_event_definition_list():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetEventDefinitions": _catalog_response(
                "GetEventDefinitions",
                "event_definition_list_xml",
                _event_definitions_doc(),
            )
        },
    )

    with _facade(handler) as magaya:
        events = magaya.catalog.events()

    assert [e.name for e in events] == ["Recolectado"]
    assert events[0].include_in_tracking is True


def test_accounts_reads_the_chart_of_accounts():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetAccountDefinitions": _catalog_response(
                "GetAccountDefinitions", "account_list_xml", _account_definitions_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        accounts = magaya.catalog.accounts()

    assert len(accounts) == 1
    assert accounts[0].type == "AccountReceivable"
    assert accounts[0].currency is not None
    assert accounts[0].currency.code == "MXN"


def test_charges_reads_the_service_list_xml_field():
    """Magaya names the output `service_list_xml` ("Items and Services")."""
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetChargeDefinitions": _catalog_response(
                "GetChargeDefinitions", "service_list_xml", _charge_definitions_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        charges = magaya.catalog.charges()

    assert len(charges) == 1
    assert charges[0].code == "AGT-INC"
    assert charges[0].amount is not None and charges[0].amount.unit == "MXN"


def test_client_charges_sends_client_uuid_not_customer_uuid():
    """The API reference documents `customer_uuid`; the live API rejects it."""
    bodies: list[str] = []
    empty_doc = f'<CustomChargeDefinitions xmlns="{_DATA_NS}"/>'
    handler = _handler_for(
        bodies,
        {
            "GetClientChargeDefinitions": _catalog_response(
                "GetClientChargeDefinitions", "charge_list_xml", empty_doc
            )
        },
    )

    with _facade(handler) as magaya:
        charges = magaya.catalog.client_charges("649383f7-d359-4720-9055-6cdb5e25d3bd")

    # A client with no custom charges yields an empty list, not an error.
    assert charges == []

    body = next(b for b in bodies if _method(b) == "GetClientChargeDefinitions")
    assert (
        '<client_uuid xsi:type="xsd:string">'
        "649383f7-d359-4720-9055-6cdb5e25d3bd</client_uuid>" in body
    )
    assert "customer_uuid" not in body


# -- the sessionless one ---------------------------------------------------


def test_ports_sends_no_access_key_and_collects_repeated_methods():
    """`GetWorkingPorts` takes no parameters; an access_key is rejected."""
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetWorkingPorts": _catalog_response(
                "GetWorkingPorts", "ports_list_xml", _ports_doc()
            )
        },
    )

    with _facade(handler) as magaya:
        ports = magaya.catalog.ports()

    assert len(ports) == 1
    assert ports[0].code == "DWC"
    assert ports[0].methods == ["Air", "Ocean"]

    body = next(b for b in bodies if _method(b) == "GetWorkingPorts")
    assert "access_key" not in body


# -- session wiring --------------------------------------------------------


def test_session_scoped_catalog_read_outside_a_with_block_raises():
    handler = _handler_for([], {})
    magaya = _facade(handler)

    with pytest.raises(SessionError):
        magaya.catalog.currencies()


def test_catalog_reads_reuse_one_session():
    bodies: list[str] = []
    handler = _handler_for(
        bodies,
        {
            "GetActiveCurrencies": _catalog_response(
                "GetActiveCurrencies", "currency_list_xml", _currencies_doc()
            ),
            "GetWorkingPorts": _catalog_response(
                "GetWorkingPorts", "ports_list_xml", _ports_doc()
            ),
        },
    )

    with _facade(handler) as magaya:
        magaya.catalog.currencies()
        magaya.catalog.ports()
        magaya.catalog.currencies()

    methods = [_method(b) for b in bodies]
    assert methods.count("StartSession") == 1
    assert methods.count("EndSession") == 1
