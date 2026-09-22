"""CLI tests for `magaya files`, `inventory`, `invoices` and `tracking`.

No network access: settings and the `Magaya` facade are monkeypatched.

The downloads get the most attention, because they are the commands that write
to the user's disk: an identifier that is not on the transaction must fail
loudly and say what IS there, an empty response must not become a zero-byte
file pretending to be a document, and a short transfer must be called out
rather than silently saved.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from typer.testing import CliRunner

from magaya_toolkit import cli
from magaya_toolkit.domain.attachment import (
    Attachment,
    AttachmentRef,
    DocumentRef,
    WebDocument,
)
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.domain.inventory import InventoryItem, ItemDefinition, WarehouseLocation
from magaya_toolkit.domain.invoice import Invoice
from magaya_toolkit.domain.shipment import Shipment

runner = CliRunner()

_PAYLOAD = b"%PDF-1.3 body"
_PAYLOAD_SIZE = len(_PAYLOAD)


class _FakeFiles:
    refs: ClassVar[list] = []
    docs: ClassVar[list] = []
    attachment_result: ClassVar[Attachment | None] = None
    document_result: ClassVar[WebDocument | None] = None

    def attachments(self, trans_type, number):
        return type(self).refs

    def documents(self, trans_type, number):
        return type(self).docs

    def attachment(self, ref):
        return type(self).attachment_result

    def document(self, ref):
        return type(self).document_result


class _FakeInventory:
    definitions_result: ClassVar[list] = []
    items_result: ClassVar[list] = []

    def definitions(self, client=""):
        return type(self).definitions_result

    def items(self, guid):
        return type(self).items_result

    def item_from_vin(self, vin):
        raise ApiError("Magaya API error: transaction_not_found")


class _FakeInvoices:
    result: ClassVar[list] = []
    calls: ClassVar[list] = []

    def query(self, *args, **kwargs):
        type(self).calls.append(("query", args, kwargs))
        return type(self).result

    def get(self, number):
        type(self).calls.append(("get", (number,), {}))
        return type(self).result[0]

    def range(self, *args, **kwargs):
        type(self).calls.append(("range", args, kwargs))
        return type(self).result


class _FakeTracking:
    calls: ClassVar[list] = []
    shipment_result: ClassVar[Shipment | None] = None

    def shipment(self, user, password, guid):
        type(self).calls.append((user, password, guid))
        return type(self).shipment_result


class _FakeMagaya:
    def __init__(self, *args, **kwargs) -> None:
        self.files = _FakeFiles()
        self.inventory = _FakeInventory()
        self.invoices = _FakeInvoices()
        self.tracking = _FakeTracking()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "MagayaSettings", lambda: object())
    monkeypatch.setattr(cli, "Magaya", _FakeMagaya)
    monkeypatch.chdir(tmp_path)
    _FakeFiles.refs = []
    _FakeFiles.docs = []
    _FakeFiles.attachment_result = None
    _FakeFiles.document_result = None
    _FakeInventory.definitions_result = []
    _FakeInventory.items_result = []
    _FakeInvoices.result = []
    _FakeInvoices.calls = []
    _FakeTracking.calls = []
    _FakeTracking.shipment_result = None


def _ref(identifier="144402385", size=_PAYLOAD_SIZE) -> AttachmentRef:
    return AttachmentRef(
        name="IN-F_78282",
        extension="pdf",
        size=size,
        owner_type="IN",
        owner_guid="inv-guid-1",
        identifier=identifier,
    )


# -- files: listing --------------------------------------------------------


def test_attachments_lists_the_identifier_first_so_it_can_be_copied():
    _FakeFiles.refs = [_ref()]

    result = runner.invoke(cli.app, ["files", "attachments", "IN", "F-78282"])

    assert result.exit_code == 0
    assert result.stdout.startswith("144402385\t")
    assert "1 attachment(s)." in result.stdout


def test_documents_says_what_the_document_is_stored_as():
    _FakeFiles.docs = [
        DocumentRef(name="BL", extension="dff", is_magaya_doc=True, identifier="144517945")
    ]

    result = runner.invoke(cli.app, ["files", "documents", "SH", "TMSE1"])

    assert "144517945" in result.stdout
    assert "stored as .dff" in result.stdout


# -- files: downloads ------------------------------------------------------


def test_get_attachment_writes_the_file_and_reports_its_size(tmp_path):
    _FakeFiles.refs = [_ref()]
    _FakeFiles.attachment_result = Attachment(
        name="IN-F_78282", extension="pdf", size=len(_PAYLOAD), data=_PAYLOAD
    )

    result = runner.invoke(
        cli.app, ["files", "get-attachment", "IN", "F-78282", "144402385"]
    )

    assert result.exit_code == 0
    written = tmp_path / "IN-F_78282.pdf"
    assert written.read_bytes() == _PAYLOAD
    assert f"({len(_PAYLOAD)} bytes)" in result.stdout


def test_get_attachment_honours_the_out_path(tmp_path):
    _FakeFiles.refs = [_ref()]
    _FakeFiles.attachment_result = Attachment(size=len(_PAYLOAD), data=_PAYLOAD)

    runner.invoke(
        cli.app,
        ["files", "get-attachment", "IN", "F-78282", "144402385", "-o", "custom.bin"],
    )

    assert (tmp_path / "custom.bin").read_bytes() == _PAYLOAD


def test_an_unknown_identifier_fails_and_lists_what_is_available():
    _FakeFiles.refs = [_ref(identifier="111"), _ref(identifier="222")]

    result = runner.invoke(cli.app, ["files", "get-attachment", "IN", "F-1", "999"])

    assert result.exit_code == 1
    assert "999" in result.stderr
    assert "111, 222" in result.stderr


def test_an_empty_response_does_not_become_a_zero_byte_file(tmp_path):
    _FakeFiles.refs = [_ref()]
    _FakeFiles.attachment_result = Attachment(name="empty", extension="pdf", data=None)

    result = runner.invoke(
        cli.app, ["files", "get-attachment", "IN", "F-78282", "144402385"]
    )

    assert result.exit_code == 1
    assert "no content" in result.stderr
    assert not (tmp_path / "empty.pdf").exists()


def test_a_short_transfer_is_called_out(tmp_path):
    """Magaya said one size and another arrived — say so before it is trusted."""
    _FakeFiles.refs = [_ref(size=9999)]
    _FakeFiles.attachment_result = Attachment(
        name="IN-F_78282", extension="pdf", size=9999, data=_PAYLOAD
    )

    result = runner.invoke(
        cli.app, ["files", "get-attachment", "IN", "F-78282", "144402385"]
    )

    assert result.exit_code == 0
    assert "truncated" in result.stderr
    # The file is still written; the caller decides what to do about it.
    assert (tmp_path / "IN-F_78282.pdf").exists()


def test_get_document_writes_a_pdf_whatever_it_is_stored_as(tmp_path):
    _FakeFiles.docs = [DocumentRef(name="BL", extension="dff", identifier="1")]
    _FakeFiles.document_result = WebDocument(data=_PAYLOAD, encoded_length=999)

    runner.invoke(cli.app, ["files", "get-document", "SH", "TMSE1", "1"])

    assert (tmp_path / "BL.pdf").read_bytes() == _PAYLOAD


# -- inventory -------------------------------------------------------------


def test_definitions_can_skip_the_ones_holding_nothing():
    _FakeInventory.definitions_result = [
        ItemDefinition(part_number="A", pieces=41, guid="g1"),
        ItemDefinition(part_number="B", pieces=0, guid="g2"),
    ]

    everything = runner.invoke(cli.app, ["inventory", "definitions"])
    stocked = runner.invoke(cli.app, ["inventory", "definitions", "--stocked"])

    assert "2 definition(s)." in everything.stdout
    assert "1 definition(s)." in stocked.stdout
    assert "B" not in stocked.stdout.split("\n")[0]


def test_items_show_where_a_piece_is_and_whether_it_moved():
    _FakeInventory.items_result = [
        InventoryItem(
            serial_number="305773",
            status="OnHand",
            location=WarehouseLocation(code="G101"),
            previous_location=WarehouseLocation(code="F101"),
            warehouse_receipt_number="WPAL-25-060",
        )
    ]

    result = runner.invoke(cli.app, ["inventory", "items", "def-guid-1"])

    assert "305773" in result.stdout
    assert "G101" in result.stdout
    assert "moved" in result.stdout


def test_an_unknown_vin_exits_non_zero():
    result = runner.invoke(cli.app, ["inventory", "vin", "1HGCM82633A004352"])

    assert result.exit_code == 1
    assert "transaction_not_found" in result.stderr


# -- invoices --------------------------------------------------------------


def test_invoices_get_renders_one_invoice():
    _FakeInvoices.result = [
        Invoice(number="F-78394", status="Paid", total_amount="532570.30", currency="MXN")
    ]

    result = runner.invoke(cli.app, ["invoices", "get", "F-78394"])

    assert "F-78394" in result.stdout
    assert "532570.30" in result.stdout


def test_invoices_range_passes_the_js_filter_arguments_in_order():
    _FakeInvoices.result = []

    runner.invoke(
        cli.app,
        [
            "invoices", "range", "--from", "2026-07-01", "--to", "2026-07-02",
            "--js-function", "byDivision", "--js-param", "DIV 1", "--js-param", "MX",
        ],
    )

    (name, _, kwargs), = _FakeInvoices.calls
    assert name == "range"
    assert kwargs["js_function"] == "byDivision"
    assert kwargs["js_params"] == ["DIV 1", "MX"]


# -- tracking --------------------------------------------------------------


def test_the_livetrack_password_is_not_a_positional_argument(monkeypatch):
    """A password in argv lands in shell history and the process list."""
    monkeypatch.setenv("MAGAYA_LIVETRACK_PASSWORD", "from-env")
    _FakeTracking.shipment_result = Shipment(number="TMSE1", mode="Ground")

    result = runner.invoke(cli.app, ["tracking", "shipment", "acme-client", "sh-guid-1"])

    assert result.exit_code == 0
    (user, password, guid), = _FakeTracking.calls
    assert (user, password, guid) == ("acme-client", "from-env", "sh-guid-1")


def test_the_password_is_prompted_for_when_not_in_the_environment(monkeypatch):
    monkeypatch.delenv("MAGAYA_LIVETRACK_PASSWORD", raising=False)
    _FakeTracking.shipment_result = Shipment(number="TMSE1", mode="Ground")

    result = runner.invoke(
        cli.app, ["tracking", "shipment", "acme-client", "sh-guid-1"], input="typed\n"
    )

    assert result.exit_code == 0
    (_, password, _), = _FakeTracking.calls
    assert password == "typed"
