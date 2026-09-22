"""CLI tests for `magaya catalog` and `magaya rates`. No network access.

The settings and the `Magaya` facade are monkeypatched, so the commands run end
to end without touching .env or the network. The fakes also record the
arguments they were called with — the point of a CLI test is that the flags
reach the SDK, not just that something printed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from magaya_toolkit import cli
from magaya_toolkit.domain.catalog import (
    AccountDefinition,
    ChargeDefinition,
    Currency,
    EventDefinition,
    Port,
)
from magaya_toolkit.domain.common import Measure
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.domain.rate import ApplicableModes, PackageRate, Rate

runner = CliRunner()


class _Recorder:
    """Returns canned results and remembers how each method was called."""

    def __init__(self, results, error: Exception | None, calls: list) -> None:
        self._results = results
        self._error = error
        self._calls = calls

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self._calls.append((name, args, kwargs))
            if self._error is not None:
                raise self._error
            return self._results
        return call


class _FakeMagaya:
    """Stand-in for the `Magaya` facade; needs no network."""

    results: ClassVar[list] = []
    error: ClassVar[Exception | None] = None
    calls: ClassVar[list] = []

    def __init__(self, *args, **kwargs) -> None:
        recorder = _Recorder(type(self).results, type(self).error, type(self).calls)
        self.catalog = recorder
        self.rates = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(cli, "MagayaSettings", lambda: object())
    monkeypatch.setattr(cli, "Magaya", _FakeMagaya)
    _FakeMagaya.results = []
    _FakeMagaya.error = None
    _FakeMagaya.calls = []


# -- catalog ---------------------------------------------------------------


def test_currencies_table_keeps_the_full_exchange_rate():
    """A rate printed through float would lose digits."""
    _FakeMagaya.results = [
        Currency(
            code="EUR",
            name="Euro",
            exchange_rate=Decimal("0.05069297294009104254"),
            is_home_currency=False,
        )
    ]

    result = runner.invoke(cli.app, ["catalog", "currencies"])

    assert result.exit_code == 0
    assert "EUR" in result.stdout
    assert "0.05069297294009104254" in result.stdout
    assert "1 currency(ies)." in result.stdout


def test_currencies_json_output_is_a_json_array():
    _FakeMagaya.results = [Currency(code="MXN", name="Mexican Peso", is_home_currency=True)]

    result = runner.invoke(cli.app, ["catalog", "currencies", "--json"])

    payload = json.loads(result.stdout)
    assert payload[0]["code"] == "MXN"
    assert payload[0]["is_home_currency"] is True


def test_ports_prints_the_code_form_the_rate_filters_expect():
    """Rate lanes take CountryCode+PortCode as one token, e.g. MXZLO."""
    _FakeMagaya.results = [
        Port(
            code="ZLO",
            name="MANZANILLO",
            country="MEXICO",
            country_code="MX",
            methods=["Ocean", "Ground"],
        )
    ]

    result = runner.invoke(cli.app, ["catalog", "ports"])

    assert "MXZLO" in result.stdout
    assert "Ocean,Ground" in result.stdout


def test_a_port_with_no_methods_prints_a_dash():
    _FakeMagaya.results = [Port(code="XXX", name="INLAND", country_code="MX", methods=[])]

    result = runner.invoke(cli.app, ["catalog", "ports"])

    assert "MXXXX" in result.stdout
    assert "1 port(s)." in result.stdout


def test_accounts_shows_the_nested_parent():
    _FakeMagaya.results = [
        AccountDefinition(
            number="511-024-000",
            type="CostOfGoodsSold",
            name="DESCONSOLIDACION",
            currency=Currency(code="MXN"),
            parent_account=AccountDefinition(number="511-000-000", name="COSTOS DE VENTA"),
        )
    ]

    result = runner.invoke(cli.app, ["catalog", "accounts"])

    assert "511-024-000" in result.stdout
    assert "parent=511-000-000" in result.stdout


def test_charges_reads_the_global_list_by_default():
    _FakeMagaya.results = [ChargeDefinition(code="AGT-INC", type="Other", description="Ganancia")]

    result = runner.invoke(cli.app, ["catalog", "charges"])

    assert "AGT-INC" in result.stdout
    assert [name for name, _, _ in _FakeMagaya.calls] == ["charges"]


def test_charges_with_a_client_reads_that_clients_overrides():
    _FakeMagaya.results = []

    result = runner.invoke(cli.app, ["catalog", "charges", "--client", "client-guid-1"])

    assert result.exit_code == 0
    (name, args, _), = _FakeMagaya.calls
    assert name == "client_charges"
    assert args == ("client-guid-1",)


def test_events_marks_the_tracked_ones():
    _FakeMagaya.results = [
        EventDefinition(name="Recolectado", include_in_tracking=True),
        EventDefinition(name="Nota interna", include_in_tracking=False),
    ]

    result = runner.invoke(cli.app, ["catalog", "events"])

    lines = [ln for ln in result.stdout.splitlines() if "\t" in ln]
    assert lines[0].endswith("tracked")
    assert not lines[1].endswith("tracked")


# -- rates -----------------------------------------------------------------


def _rate() -> Rate:
    return Rate(
        type="Standard",
        origin_country_code="MX",
        destination_country_code="US",
        apply_by="Package",
        currency=Currency(code="MXN"),
        applicable_modes=ApplicableModes(methods=["Ground"]),
        package_rates=[],
    )


def test_standard_rates_render_the_lane_and_mode():
    _FakeMagaya.results = [_rate()]

    result = runner.invoke(cli.app, ["rates", "standard"])

    assert "MX->US" in result.stdout
    assert "Ground" in result.stdout
    assert "Package" in result.stdout
    assert "1 rate(s)." in result.stdout


def test_the_lane_filter_reaches_the_sdk():
    _FakeMagaya.results = []

    runner.invoke(
        cli.app,
        ["rates", "standard", "--origin", "MXZLO", "--destination", "USLAX", "--method", "Ocean"],
    )

    (name, _, kwargs), = _FakeMagaya.calls
    assert name == "standard"
    assert kwargs == {"org_port": "MXZLO", "dest_port": "USLAX", "method": "Ocean"}


def test_client_rates_pass_the_guid_and_include_standard():
    _FakeMagaya.results = []

    runner.invoke(cli.app, ["rates", "client", "client-guid-1", "--include-standard"])

    (name, args, kwargs), = _FakeMagaya.calls
    assert name == "for_client"
    assert args == ("client-guid-1",)
    assert kwargs["include_standard"] is True


def test_carrier_rates_pass_the_guid():
    _FakeMagaya.results = []

    runner.invoke(cli.app, ["rates", "carrier", "carrier-guid-1", "--origin", "MXZLO"])

    (name, args, kwargs), = _FakeMagaya.calls
    assert name == "for_carrier"
    assert args == ("carrier-guid-1",)
    assert kwargs["org_port"] == "MXZLO"


def test_rates_with_prices_render_them_with_the_currency():
    rate = _rate()
    rate.package_rates = [PackageRate(price=Measure(value=Decimal("50.00"), unit="MXN"))]
    _FakeMagaya.results = [rate]

    result = runner.invoke(cli.app, ["rates", "standard"])

    assert "50.00 MXN" in result.stdout


# -- failure ---------------------------------------------------------------


def test_an_api_error_exits_non_zero_with_a_message():
    _FakeMagaya.error = ApiError("Magaya API error: invalid_operation")

    result = runner.invoke(cli.app, ["rates", "standard", "--origin", "BADPORT"])

    assert result.exit_code == 1
    assert "invalid_operation" in result.stderr
