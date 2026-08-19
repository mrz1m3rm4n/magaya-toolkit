"""Unit tests for LxmlInvoiceParser. No network access.

Canned <Invoice> documents exercise the namespace-aware, direct-children-only
parsing rules that matter against the real Magaya XML — notably that a deep
<Number> inside a nested <CreatedBy> entity must NOT win over the invoice's own.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.invoice_parser import LxmlInvoiceParser

_NS = "http://www.magaya.com/XMLSchema/V1"

# A single-transaction GetTransaction(IN) response: the <Invoice> element is the
# ROOT itself. A nested <CreatedBy> hides a deep <Number> (inside CustomFields)
# that must NOT be read as the invoice number; <Entity>/<Name> is the bill-to.
_ONE_INVOICE = f"""<?xml version="1.0" encoding="utf-8"?>
<Invoice xmlns="{_NS}" GUID="inv-guid-1" Type="IN">
  <Number>F-78282</Number>
  <Status>Open</Status>
  <TotalAmount Currency="MXN">1500.00</TotalAmount>
  <Currency Code="MXN">
    <Name>Mexican Peso</Name>
    <ExchangeRate>1.00</ExchangeRate>
    <IsHomeCurrency>true</IsHomeCurrency>
  </Currency>
  <HomeCurrency Code="MXN">
    <Name>Mexican Peso</Name>
  </HomeCurrency>
  <IsPrinted>true</IsPrinted>
  <HasAttachments>false</HasAttachments>
  <Entity>
    <Name>Acme Client Corp</Name>
  </Entity>
  <IssuedBy>
    <Name>Weport Global</Name>
  </IssuedBy>
  <CreatedBy>
    <Name>Some User</Name>
    <CustomFields>
      <Field><Number>SHOULD-NOT-WIN</Number></Field>
    </CustomFields>
  </CreatedBy>
</Invoice>"""


def test_parse_one_reads_root_element_as_the_invoice():
    invoice = LxmlInvoiceParser().parse_one(_ONE_INVOICE)

    assert invoice.guid == "inv-guid-1"
    assert invoice.type_code == "IN"
    # Direct-children-only: the nested <Number> inside <CreatedBy> must not win.
    assert invoice.number == "F-78282"
    assert invoice.status == "Open"
    assert invoice.total_amount == Decimal("1500.00")
    # Currency code lives in the `Code` attribute, not element text.
    assert invoice.currency == "MXN"
    assert invoice.home_currency == "MXN"
    assert invoice.is_printed is True
    assert invoice.has_attachments is False
    # Nested <Name> grandchildren.
    assert invoice.entity_name == "Acme Client Corp"
    assert invoice.issued_by_name == "Weport Global"


def test_parse_one_rejects_a_shipments_batch():
    with pytest.raises(XmlValidationError):
        LxmlInvoiceParser().parse_one(f'<Shipments xmlns="{_NS}"/>')


def test_parse_one_rejects_wrong_single_element():
    with pytest.raises(XmlValidationError):
        LxmlInvoiceParser().parse_one(
            f'<OceanShipment xmlns="{_NS}" GUID="x" Type="SH"/>'
        )


def test_parse_one_malformed_xml_raises_validation_error():
    with pytest.raises(XmlValidationError):
        LxmlInvoiceParser().parse_one("<Invoice><Broken></Invoice>")
