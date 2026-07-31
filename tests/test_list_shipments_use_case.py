"""Unit tests for the list_shipments use case. No network access.

A fake reader yields canned <Shipments> chunks (parsed by the real
LxmlShipmentParser) so dedupe-by-guid and max_results truncation are exercised
end to end through the parser.
"""

from __future__ import annotations

from collections.abc import Iterator

from magaya_toolkit.application.use_cases import list_shipments
from magaya_toolkit.infrastructure.xml.shipment_parser import LxmlShipmentParser

_NS = "http://www.magaya.com/XMLSchema/V1"


def _shipment(guid: str, number: str) -> str:
    return (
        f'<OceanShipment GUID="{guid}" Type="SH">'
        f"<Number>{number}</Number>"
        "</OceanShipment>"
    )


def _doc(*inner: str) -> str:
    return f'<Shipments xmlns="{_NS}">{"".join(inner)}</Shipments>'


class _FakeReader:
    """Yields the given chunks and records the arguments it was called with."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.calls: list[dict] = []

    def read_transactions_by_date(
        self,
        trans_type: str,
        start_date: str,
        end_date: str,
        record_quantity: int = 5,
        backwards_order: bool = False,
        flags: int = 0,
    ) -> Iterator[str]:
        self.calls.append(
            {
                "trans_type": trans_type,
                "start_date": start_date,
                "end_date": end_date,
                "record_quantity": record_quantity,
                "backwards_order": backwards_order,
            }
        )
        yield from self._chunks


def test_dedupes_by_guid_across_chunks():
    # "dup" appears in both chunks; "a" and "b" are unique.
    chunk1 = _doc(_shipment("dup", "SH-1"), _shipment("a", "SH-2"))
    chunk2 = _doc(_shipment("dup", "SH-1-again"), _shipment("b", "SH-3"))
    reader = _FakeReader([chunk1, chunk2])

    result = list_shipments(
        reader=reader,
        parser=LxmlShipmentParser(),
        start_date="2025-01-01",
        end_date="2025-01-31",
    )

    guids = [s.guid for s in result]
    assert guids == ["dup", "a", "b"]  # first "dup" kept, second dropped
    # First occurrence wins: keeps the original number, not the later one.
    assert result[0].number == "SH-1"


def test_shipments_without_guid_are_always_kept():
    inner = (
        '<OceanShipment Type="SH"><Number>NO-GUID-1</Number></OceanShipment>'
        '<OceanShipment Type="SH"><Number>NO-GUID-2</Number></OceanShipment>'
    )
    reader = _FakeReader([_doc(inner)])

    result = list_shipments(
        reader=reader,
        parser=LxmlShipmentParser(),
        start_date="2025-01-01",
        end_date="2025-01-31",
    )

    assert [s.number for s in result] == ["NO-GUID-1", "NO-GUID-2"]
    assert all(s.guid is None for s in result)


def test_max_results_truncates():
    chunk = _doc(
        _shipment("a", "SH-1"),
        _shipment("b", "SH-2"),
        _shipment("c", "SH-3"),
    )
    reader = _FakeReader([chunk])

    result = list_shipments(
        reader=reader,
        parser=LxmlShipmentParser(),
        start_date="2025-01-01",
        end_date="2025-01-31",
        max_results=2,
    )

    assert len(result) == 2
    assert [s.guid for s in result] == ["a", "b"]


def test_forwards_query_arguments_to_reader():
    reader = _FakeReader([_doc(_shipment("a", "SH-1"))])

    list_shipments(
        reader=reader,
        parser=LxmlShipmentParser(),
        start_date="2025-01-01",
        end_date="2025-01-31",
        trans_type="SH",
        record_quantity=10,
        backwards_order=True,
    )

    assert reader.calls == [
        {
            "trans_type": "SH",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "record_quantity": 10,
            "backwards_order": True,
        }
    ]
