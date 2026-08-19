"""Tests for the `entities` resource on the `Magaya` facade. No network access.

An httpx.MockTransport feeds canned SOAP responses (namespaced under
urn:CSSoapService, entity/contact XML HTML-escaped) so the facade drives the
real SOAP client and parser end to end. These tests prove the resource reads
through the managed session, picks GetEntities vs GetEntitiesOfType by whether a
type is given, and refuses to work before the session is open.
"""

from __future__ import annotations

from collections.abc import Callable
from xml.sax.saxutils import escape

import httpx
import pytest

from magaya_toolkit import Magaya
from magaya_toolkit.domain.entity import EntityType
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


def _entities_response(method: str, entity_list_xml: str) -> str:
    return _soap(
        f"<snp:{method}Response {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:entity_list_xml>{escape(entity_list_xml)}</snp:entity_list_xml>"
        f"</snp:{method}Response>"
    )


def _contacts_response(contact_list_xml: str) -> str:
    return _soap(
        f"<snp:GetEntityContactsResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:contact_list_xml>{escape(contact_list_xml)}</snp:contact_list_xml>"
        "</snp:GetEntityContactsResponse>"
    )


def _entity_transactions_response(acctrans_list_xml: str) -> str:
    return _soap(
        f"<snp:GetEntityTransactionsResponse {_NS}>"
        f"<snp:return>no_error</snp:return>"
        f"<snp:acctrans_list_xml>{escape(acctrans_list_xml)}</snp:acctrans_list_xml>"
        "</snp:GetEntityTransactionsResponse>"
    )


def _guid_items_doc() -> str:
    return (
        f'<GUIDItems xmlns="{_DATA_NS}">'
        "<GUIDItem><GUID>inv-guid-1</GUID><Type>Invoice</Type></GUIDItem>"
        "</GUIDItems>"
    )


def _entities_doc() -> str:
    return (
        f'<Entities xmlns="{_DATA_NS}">'
        '<Client GUID="c1"><Name>Acme</Name><EntityID>CUST-1</EntityID></Client>'
        "</Entities>"
    )


def _contacts_doc() -> str:
    return (
        f'<EntityContacts xmlns="{_DATA_NS}">'
        '<EntityContact GUID="k1"><Name>Desk</Name>'
        "<Address><ContactEmail>desk@acme.test</ContactEmail></Address>"
        "</EntityContact>"
        "</EntityContacts>"
    )


def _method(body: str) -> str | None:
    for method in (
        "StartSession",
        "GetEntitiesOfType",
        "GetEntities",
        "GetEntityContacts",
        "GetEntityTransactions",
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


def test_find_with_type_uses_get_entities_of_type_and_sends_entity_type():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetEntitiesOfType":
            text = _entities_response("GetEntitiesOfType", _entities_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        results = magaya.entities.find("MUE", entity_type=EntityType.CLIENT)

    assert [e.name for e in results] == ["Acme"]
    assert [e.kind for e in results] == ["Client"]

    of_type_body = next(b for b in bodies if _method(b) == "GetEntitiesOfType")
    assert '<entity_type xsi:type="xsd:int">2</entity_type>' in of_type_body
    assert "<start_with" in of_type_body and "MUE" in of_type_body


def test_find_without_type_uses_get_entities_without_entity_type():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetEntities":
            text = _entities_response("GetEntities", _entities_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        results = magaya.entities.find()

    assert [e.name for e in results] == ["Acme"]
    # GetEntities was used and no entity_type element was sent.
    methods = [_method(b) for b in bodies]
    assert "GetEntities" in methods
    assert "GetEntitiesOfType" not in methods
    get_entities_body = next(b for b in bodies if _method(b) == "GetEntities")
    assert "entity_type" not in get_entities_body


def test_contacts_returns_contacts():
    def handler(request: httpx.Request) -> httpx.Response:
        method = _method(request.content.decode("utf-8"))
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetEntityContacts":
            text = _contacts_response(_contacts_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        contacts = magaya.entities.contacts("c1")

    assert [c.name for c in contacts] == ["Desk"]
    assert contacts[0].contact_email == "desk@acme.test"


def test_transactions_reads_refs_and_sends_entity_uuid_and_dates():
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        bodies.append(body)
        method = _method(body)
        if method == "StartSession":
            text = _start_session_response(999)
        elif method == "GetEntityTransactions":
            text = _entity_transactions_response(_guid_items_doc())
        else:
            text = _end_session_response()
        return httpx.Response(200, text=text, headers={"Content-Type": "text/xml"})

    with _facade(handler) as magaya:
        refs = magaya.entities.transactions("ent-guid-1", "2026-07-01", "2026-07-31")

    assert len(refs) == 1
    assert refs[0].guid == "inv-guid-1"
    assert refs[0].type == "Invoice"

    tx_body = next(b for b in bodies if _method(b) == "GetEntityTransactions")
    assert '<entity_uuid xsi:type="xsd:string">ent-guid-1</entity_uuid>' in tx_body
    assert '<start_date xsi:type="xsd:string">2026-07-01</start_date>' in tx_body
    assert '<end_date xsi:type="xsd:string">2026-07-31</end_date>' in tx_body


def test_using_entities_before_open_raises_session_error():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request should be made before the session is open")

    magaya = _facade(handler)
    with pytest.raises(SessionError):
        magaya.entities.find()
    with pytest.raises(SessionError):
        magaya.entities.contacts("c1")
    with pytest.raises(SessionError):
        magaya.entities.transactions("c1", "2026-07-01", "2026-07-31")
