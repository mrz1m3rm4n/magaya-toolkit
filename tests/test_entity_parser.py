"""Unit tests for LxmlEntityParser. No network access.

Canned <Entities> and <EntityContacts> documents exercise the namespace-aware,
direct-children-only parsing rules that matter against the real Magaya XML.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.entity_parser import LxmlEntityParser

_NS = "http://www.magaya.com/XMLSchema/V1"

# A full <Client> (Address with TWO <Street>, BillingAddress, Balance with a
# Currency, IsPrepaid) plus a sparse <Carrier> (IsInactive, no address).
_ENTITIES = f"""<?xml version="1.0" encoding="utf-8"?>
<Entities xmlns="{_NS}">
  <Client GUID="client-guid-1">
    <Type>Client</Type>
    <Name>Acme Corp</Name>
    <EntityID>CUST-001</EntityID>
    <AccountNumber>ACC-9</AccountNumber>
    <CreatedOn>2025-01-15T09:30:00</CreatedOn>
    <Email>ops@acme.test</Email>
    <Phone>+1-555-0100</Phone>
    <ContactFirstName>Jane</ContactFirstName>
    <ContactLastName>Doe</ContactLastName>
    <ExporterID>EX-42</ExporterID>
    <ExporterIDType>EIN</ExporterIDType>
    <Balance Currency="USD">1234.50</Balance>
    <IsPrepaid>true</IsPrepaid>
    <Address>
      <Street>Suite 500</Street>
      <Street>123 Main St</Street>
      <City>Miami</City>
      <State>FL</State>
      <ZipCode>33101</ZipCode>
      <Country Code="US">United States</Country>
      <ContactName>Jane Doe</ContactName>
      <ContactPhone>+1-555-0101</ContactPhone>
      <ContactEmail>jane@acme.test</ContactEmail>
    </Address>
    <BillingAddress>
      <Street>PO Box 9</Street>
      <City>Miami</City>
    </BillingAddress>
  </Client>
  <Carrier GUID="carrier-guid-2">
    <Type>Carrier</Type>
    <Name>Fast Freight</Name>
    <IsInactive>false</IsInactive>
  </Carrier>
</Entities>"""

_CONTACTS = f"""<?xml version="1.0" encoding="utf-8"?>
<EntityContacts xmlns="{_NS}">
  <EntityContact GUID="contact-guid-1">
    <Type>Contact</Type>
    <Name>Support Desk</Name>
    <CreatedOn>2025-02-01T10:00:00</CreatedOn>
    <Address>
      <ContactName>Support Desk</ContactName>
      <ContactPhone>+1-555-0199</ContactPhone>
      <ContactEmail>support@acme.test</ContactEmail>
    </Address>
    <BillingAddress/>
  </EntityContact>
</EntityContacts>"""


def test_parses_entities_deriving_kind_from_tag():
    entities = LxmlEntityParser().parse_entities(_ENTITIES)
    assert len(entities) == 2

    client, carrier = entities

    # Kind derived from the element local-name; guid from the attribute.
    assert client.kind == "Client"
    assert client.guid == "client-guid-1"
    assert carrier.kind == "Carrier"
    assert carrier.guid == "carrier-guid-2"

    assert client.name == "Acme Corp"
    assert client.entity_id == "CUST-001"
    assert client.account_number == "ACC-9"
    assert client.type == "Client"
    assert client.email == "ops@acme.test"
    assert client.contact_first_name == "Jane"
    assert client.exporter_id == "EX-42"

    # Booleans and datetimes.
    assert client.is_prepaid is True
    assert carrier.is_inactive is False
    assert isinstance(client.created_on, datetime)
    assert client.created_on == datetime.fromisoformat("2025-01-15T09:30:00")

    # Balance -> Measure(value, unit=Currency attr).
    assert client.balance is not None
    assert client.balance.value == Decimal("1234.50")
    assert client.balance.unit == "USD"

    # Address: ALL <Street> lines collected into a list, in order.
    assert client.address is not None
    assert client.address.street == ["Suite 500", "123 Main St"]
    assert client.address.city == "Miami"
    assert client.address.country == "United States"
    assert client.address.country_code == "US"
    assert client.address.contact_email == "jane@acme.test"

    # BillingAddress parsed independently.
    assert client.billing_address is not None
    assert client.billing_address.street == ["PO Box 9"]

    # Sparse carrier: absent fields default to None, no error.
    assert carrier.address is None
    assert carrier.balance is None
    assert carrier.is_prepaid is None


def test_empty_entities_returns_empty_list():
    doc = f'<Entities xmlns="{_NS}"/>'
    assert LxmlEntityParser().parse_entities(doc) == []


def test_wrong_entities_root_raises_validation_error():
    with pytest.raises(XmlValidationError):
        LxmlEntityParser().parse_entities(f'<Other xmlns="{_NS}"/>')


def test_parses_contacts_reading_address_fields():
    contacts = LxmlEntityParser().parse_contacts(_CONTACTS)
    assert len(contacts) == 1

    contact = contacts[0]
    assert contact.guid == "contact-guid-1"
    assert contact.name == "Support Desk"
    assert contact.type == "Contact"
    assert contact.created_on == datetime.fromisoformat("2025-02-01T10:00:00")
    # Name/phone/email come from the contact's own <Address>.
    assert contact.contact_name == "Support Desk"
    assert contact.contact_phone == "+1-555-0199"
    assert contact.contact_email == "support@acme.test"


def test_empty_contacts_returns_empty_list():
    doc = f'<EntityContacts xmlns="{_NS}"/>'
    assert LxmlEntityParser().parse_contacts(doc) == []
