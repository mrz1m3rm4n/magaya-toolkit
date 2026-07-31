"""CLI tests for `magaya shipments`. No network access.

The settings, SOAP client, and use case are monkeypatched so the command runs
end to end without touching .env or the network.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from typer.testing import CliRunner

from magaya_toolkit import cli
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.domain.shipment import Measure, Shipment

runner = CliRunner()


class _FakeClient:
    """Stand-in for MagayaSoapClient that records close() and needs no network."""

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # MagayaSettings() would read .env / env vars; replace it entirely.
    monkeypatch.setattr(cli, "MagayaSettings", lambda: object())
    monkeypatch.setattr(cli, "MagayaSoapClient", _FakeClient)


def _sample() -> Shipment:
    return Shipment(
        guid="g-1",
        number="OCEAN-001",
        mode="Ocean",
        direction="Export",
        status="In Transit",
        shipper_name="Acme Corp",
        consignee_name="Globex",
        total_weight=Measure(value="1234.5", unit="kg"),
        estimated_arrival=datetime.fromisoformat("2025-02-01T12:00:00"),
    )


def test_shipments_table_output(monkeypatch):
    monkeypatch.setattr(cli, "list_shipments", lambda **kwargs: [_sample()])

    result = runner.invoke(
        cli.app, ["shipments", "--from", "2025-01-01", "--to", "2025-01-31"]
    )

    assert result.exit_code == 0
    assert "OCEAN-001" in result.stdout
    assert "Acme Corp -> Globex" in result.stdout
    assert "ETA=2025-02-01" in result.stdout
    assert "1 shipment(s)." in result.stdout


def test_shipments_json_output(monkeypatch):
    monkeypatch.setattr(cli, "list_shipments", lambda **kwargs: [_sample()])

    result = runner.invoke(
        cli.app, ["shipments", "--from", "2025-01-01", "--to", "2025-01-31", "--json"]
    )

    assert result.exit_code == 0
    assert '"number": "OCEAN-001"' in result.stdout
    assert '"mode": "Ocean"' in result.stdout


def test_shipments_api_error_exits_1(monkeypatch):
    def _raise(**kwargs):
        raise ApiError("access_denied")

    monkeypatch.setattr(cli, "list_shipments", _raise)

    result = runner.invoke(
        cli.app, ["shipments", "--from", "2025-01-01", "--to", "2025-01-31"]
    )

    assert result.exit_code == 1
