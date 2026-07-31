"""CLI tests for `magaya shipments`. No network access.

The settings and the `Magaya` facade are monkeypatched so the command runs end
to end without touching .env or the network. A fake facade stands in for the
real SDK front door and records that its session is opened and closed.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from magaya_toolkit import cli
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.domain.shipment import Measure, Shipment

runner = CliRunner()


class _FakeShipments:
    """Stand-in for `ShipmentsResource`; returns canned shipments."""

    def __init__(self, results, error: Exception | None) -> None:
        self._results = results
        self._error = error

    def list(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return self._results


class _FakeMagaya:
    """Stand-in for the `Magaya` facade; records open/close, needs no network."""

    results: ClassVar[list] = []
    error: ClassVar[Exception | None] = None

    def __init__(self, *args, **kwargs) -> None:
        self.opened = False
        self.closed = False
        self.shipments = _FakeShipments(type(self).results, type(self).error)

    def __enter__(self):
        self.opened = True
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # MagayaSettings() would read .env / env vars; replace it entirely.
    monkeypatch.setattr(cli, "MagayaSettings", lambda: object())
    monkeypatch.setattr(cli, "Magaya", _FakeMagaya)
    _FakeMagaya.results = []
    _FakeMagaya.error = None


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


def test_shipments_table_output():
    _FakeMagaya.results = [_sample()]

    result = runner.invoke(
        cli.app, ["shipments", "--from", "2025-01-01", "--to", "2025-01-31"]
    )

    assert result.exit_code == 0
    assert "OCEAN-001" in result.stdout
    assert "Acme Corp -> Globex" in result.stdout
    assert "ETA=2025-02-01" in result.stdout
    assert "1 shipment(s)." in result.stdout


def test_shipments_json_output():
    _FakeMagaya.results = [_sample()]

    result = runner.invoke(
        cli.app, ["shipments", "--from", "2025-01-01", "--to", "2025-01-31", "--json"]
    )

    assert result.exit_code == 0
    assert '"number": "OCEAN-001"' in result.stdout
    assert '"mode": "Ocean"' in result.stdout


def test_shipments_api_error_exits_1():
    _FakeMagaya.error = ApiError("access_denied")

    result = runner.invoke(
        cli.app, ["shipments", "--from", "2025-01-01", "--to", "2025-01-31"]
    )

    assert result.exit_code == 1
