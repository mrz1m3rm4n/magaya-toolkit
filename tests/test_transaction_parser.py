"""Unit tests for LxmlGuidItemsParser. No network access.

Canned <GUIDItems> documents exercise the namespace-aware, direct-children-only
parsing of QueryLog results into TransactionRef read models.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.transaction_parser import LxmlGuidItemsParser

_NS = "http://www.magaya.com/XMLSchema/V1"

_TWO_ITEMS = f"""<?xml version="1.0" encoding="utf-8"?>
<GUIDItems xmlns="{_NS}">
  <GUIDItem>
    <GUID>guid-1</GUID>
    <Type>Invoice</Type>
    <LogType>Creation</LogType>
    <LogDate>2026-07-01T10:10:17-06:00</LogDate>
  </GUIDItem>
  <GUIDItem>
    <GUID>guid-2</GUID>
    <Type>Invoice</Type>
    <LogType>Edition</LogType>
    <LogDate>2026-07-02T08:00:00-06:00</LogDate>
  </GUIDItem>
</GUIDItems>"""


def test_parses_two_guid_items_into_transaction_refs():
    refs = LxmlGuidItemsParser().parse(_TWO_ITEMS)
    assert len(refs) == 2

    first, second = refs

    assert first.guid == "guid-1"
    assert first.type == "Invoice"
    assert first.log_type == "Creation"
    assert isinstance(first.log_date, datetime)
    assert first.log_date == datetime.fromisoformat("2026-07-01T10:10:17-06:00")

    assert second.guid == "guid-2"
    assert second.log_type == "Edition"
    assert second.log_date == datetime.fromisoformat("2026-07-02T08:00:00-06:00")


def test_empty_guid_items_returns_empty_list():
    doc = f'<GUIDItems xmlns="{_NS}"/>'
    assert LxmlGuidItemsParser().parse(doc) == []


def test_malformed_xml_raises_validation_error():
    with pytest.raises(XmlValidationError):
        LxmlGuidItemsParser().parse("<GUIDItems><Broken></GUIDItems>")


def test_wrong_root_raises_validation_error():
    with pytest.raises(XmlValidationError):
        LxmlGuidItemsParser().parse(f'<Other xmlns="{_NS}"/>')
