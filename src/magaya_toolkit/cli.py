"""Command-line entry point.

Read-only. Every command takes `--json` and prints a JSON array instead of the
tab-separated table, so output pipes straight into `jq`.

    magaya shipments --from 2025-01-01 --to 2025-01-31
    magaya entities MUE --type client --json

    magaya catalog currencies
    magaya catalog ports --json
    magaya catalog charges --client <GUID>

    magaya rates standard --method Ocean
    magaya rates client <GUID> --include-standard
    magaya rates carrier <GUID> --origin MXZLO
"""

from __future__ import annotations

import json

import typer

from magaya_toolkit.domain.entity import EntityType
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.facade import Magaya
from magaya_toolkit.infrastructure.config import MagayaSettings

# Map the CLI `--type` choices to the domain `EntityType` codes. `None` (the
# option's default) means "all entities" (no type filter).
_ENTITY_TYPES = {
    "client": EntityType.CLIENT,
    "customer": EntityType.CLIENT,  # alias — Magaya's API name for the client type
    "carrier": EntityType.CARRIER,
    "vendor": EntityType.VENDOR,
    "forwarding-agent": EntityType.FORWARDING_AGENT,
    "warehouse-provider": EntityType.WAREHOUSE_PROVIDER,
    "employee": EntityType.EMPLOYEE,
    "salesman": EntityType.SALESMAN,
    "division": EntityType.DIVISION,
}

app = typer.Typer(help="Read data from the Magaya API.")

catalog_app = typer.Typer(help="Read the reference data this install is configured with.")
rates_app = typer.Typer(help="Read freight rates.")
app.add_typer(catalog_app, name="catalog")
app.add_typer(rates_app, name="rates")


@app.callback()
def main() -> None:
    """Magaya toolkit CLI. Run a subcommand (e.g. `shipments` or `catalog`)."""


def _read(read):
    """Run `read(magaya)` in a managed session, reporting `ApiError` cleanly."""
    settings = MagayaSettings()
    try:
        with Magaya(settings) as magaya:
            return read(magaya)
    except ApiError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


def _emit(results, noun: str, row, as_json: bool) -> None:
    """Print `results` as JSON or as one tab-separated line each, then a count."""
    if as_json:
        typer.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
        return
    for result in results:
        typer.echo(row(result))
    typer.echo(f"{len(results)} {noun}.")


def _json_option() -> bool:
    return typer.Option(False, "--json", help="Emit a JSON array instead of a table.")


def _eta(shipment) -> str:
    """Format a shipment's estimated arrival as a plain date, or '-'."""
    if shipment.estimated_arrival is None:
        return "-"
    return shipment.estimated_arrival.date().isoformat()


@app.command()
def shipments(
    from_date: str = typer.Option(..., "--from", help="Start date (yyyy-MM-dd)."),
    to_date: str = typer.Option(..., "--to", help="End date (yyyy-MM-dd)."),
    trans_type: str = typer.Option("SH", "--type", help="Transaction type."),
    record_quantity: int = typer.Option(5, "--record-quantity", help="Records per batch."),
    max_results: int | None = typer.Option(None, "--max", help="Cap the number of shipments."),
    as_json: bool = typer.Option(False, "--json", help="Emit a JSON array instead of a table."),
    backwards: bool = typer.Option(
        False, "--backwards/--no-backwards", help="Read newest-first."
    ),
) -> None:
    """List shipments from Magaya for a date range (read-only)."""
    settings = MagayaSettings()
    try:
        with Magaya(settings) as magaya:
            results = magaya.shipments.list(
                from_date,
                to_date,
                trans_type=trans_type,
                record_quantity=record_quantity,
                backwards=backwards,
                max_results=max_results,
            )
    except ApiError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if as_json:
        payload = [shipment.model_dump(mode="json") for shipment in results]
        typer.echo(json.dumps(payload, indent=2))
        return

    for shipment in results:
        route = f"{shipment.shipper_name or '-'} -> {shipment.consignee_name or '-'}"
        typer.echo(
            f"{shipment.number}\t"
            f"{shipment.mode}\t"
            f"{shipment.direction or '-'}\t"
            f"{shipment.status or '-'}\t"
            f"{route}\t"
            f"ETA={_eta(shipment)}"
        )
    typer.echo(f"{len(results)} shipment(s).")


@app.command()
def entities(
    start_with: str = typer.Argument("", help="Filter entities by name prefix."),
    entity_type: str | None = typer.Option(
        None,
        "--type",
        help=(
            "Filter by entity type: client, carrier, vendor, forwarding-agent, "
            "warehouse-provider, employee, salesman, division. Omit for all."
        ),
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit a JSON array instead of a table."),
) -> None:
    """List entities from Magaya (read-only)."""
    if entity_type is not None and entity_type not in _ENTITY_TYPES:
        choices = ", ".join(sorted(_ENTITY_TYPES))
        typer.secho(
            f"ERROR: unknown --type '{entity_type}'. Choose one of: {choices}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    selected_type = _ENTITY_TYPES[entity_type] if entity_type is not None else None

    settings = MagayaSettings()
    try:
        with Magaya(settings) as magaya:
            results = magaya.entities.find(start_with, entity_type=selected_type)
    except ApiError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if as_json:
        payload = [entity.model_dump(mode="json") for entity in results]
        typer.echo(json.dumps(payload, indent=2))
        return

    for entity in results:
        typer.echo(
            f"{entity.name or '-'}\t"
            f"{entity.kind}\t"
            f"{entity.entity_id or '-'}\t"
            f"{entity.email or '-'}\t"
            f"{entity.phone or '-'}"
        )
    typer.echo(f"{len(results)} entity(ies).")


# -- catalog ---------------------------------------------------------------


@catalog_app.command("currencies")
def catalog_currencies(as_json: bool = _json_option()) -> None:
    """List the active currencies and their exchange rates."""
    results = _read(lambda m: m.catalog.currencies())
    _emit(
        results,
        "currency(ies)",
        lambda c: (
            f"{c.code or '-'}\t"
            f"{c.name or '-'}\t"
            f"{c.exchange_rate if c.exchange_rate is not None else '-'}\t"
            f"{'home' if c.is_home_currency else ''}"
        ),
        as_json,
    )


@catalog_app.command("accounts")
def catalog_accounts(as_json: bool = _json_option()) -> None:
    """List the chart of accounts."""
    results = _read(lambda m: m.catalog.accounts())
    _emit(
        results,
        "account(s)",
        lambda a: (
            f"{a.number or '-'}\t"
            f"{a.type or '-'}\t"
            f"{a.name or '-'}\t"
            f"{a.currency.code if a.currency else '-'}\t"
            f"parent={a.parent_account.number if a.parent_account else '-'}"
        ),
        as_json,
    )


@catalog_app.command("charges")
def catalog_charges(
    client: str | None = typer.Option(
        None, "--client", help="Read one client's custom charges instead of the global list."
    ),
    as_json: bool = _json_option(),
) -> None:
    """List the item/service (charge) definitions."""
    if client is None:
        results = _read(lambda m: m.catalog.charges())
    else:
        results = _read(lambda m: m.catalog.client_charges(client))
    _emit(
        results,
        "charge(s)",
        lambda c: (
            f"{c.code or '-'}\t"
            f"{c.type or '-'}\t"
            f"{c.description or '-'}\t"
            f"{c.account_definition.name if c.account_definition else '-'}"
        ),
        as_json,
    )


@catalog_app.command("events")
def catalog_events(as_json: bool = _json_option()) -> None:
    """List the tracking-event definitions this install can stamp."""
    results = _read(lambda m: m.catalog.events())
    _emit(
        results,
        "event(s)",
        lambda e: f"{e.name or '-'}\t{'tracked' if e.include_in_tracking else ''}",
        as_json,
    )


@catalog_app.command("ports")
def catalog_ports(as_json: bool = _json_option()) -> None:
    """List the working ports.

    The first column is the CountryCode+PortCode form the rate filters expect.
    """
    results = _read(lambda m: m.catalog.ports())
    _emit(
        results,
        "port(s)",
        lambda p: (
            f"{(p.country_code or '')}{p.code or ''}\t"
            f"{p.name or '-'}\t"
            f"{p.country or '-'}\t"
            f"{','.join(p.methods) or '-'}"
        ),
        as_json,
    )


# -- rates -----------------------------------------------------------------


def _rate_row(rate) -> str:
    lane = f"{rate.origin_country_code or '?'}->{rate.destination_country_code or '?'}"
    modes = ",".join(rate.applicable_modes.methods) if rate.applicable_modes else ""
    prices = ",".join(str(p) for p in rate.prices) or "-"
    charge = rate.charge_definition.code if rate.charge_definition else "-"
    return (
        f"{rate.type or '-'}\t"
        f"{lane}\t"
        f"{modes or '-'}\t"
        f"{charge}\t"
        f"{rate.apply_by or '-'}\t"
        f"{prices} {rate.currency.code if rate.currency else ''}".rstrip()
    )


@rates_app.command("standard")
def rates_standard(
    origin: str = typer.Option("", "--origin", help="Origin port, CountryCode+PortCode."),
    destination: str = typer.Option("", "--destination", help="Destination port."),
    method: str = typer.Option("", "--method", help="Air, Ocean or Ground."),
    as_json: bool = _json_option(),
) -> None:
    """List the standard (house) rates."""
    results = _read(
        lambda m: m.rates.standard(org_port=origin, dest_port=destination, method=method)
    )
    _emit(results, "rate(s)", _rate_row, as_json)


@rates_app.command("client")
def rates_client(
    guid: str = typer.Argument(..., help="Client GUID."),
    origin: str = typer.Option("", "--origin", help="Origin port, CountryCode+PortCode."),
    destination: str = typer.Option("", "--destination", help="Destination port."),
    method: str = typer.Option("", "--method", help="Air, Ocean or Ground."),
    include_standard: bool = typer.Option(
        False, "--include-standard", help="Also return the standard rates that apply."
    ),
    as_json: bool = _json_option(),
) -> None:
    """List one client's negotiated rates."""
    results = _read(
        lambda m: m.rates.for_client(
            guid,
            org_port=origin,
            dest_port=destination,
            method=method,
            include_standard=include_standard,
        )
    )
    _emit(results, "rate(s)", _rate_row, as_json)


@rates_app.command("carrier")
def rates_carrier(
    guid: str = typer.Argument(..., help="Carrier GUID."),
    origin: str = typer.Option("", "--origin", help="Origin port, CountryCode+PortCode."),
    destination: str = typer.Option("", "--destination", help="Destination port."),
    method: str = typer.Option("", "--method", help="Air, Ocean or Ground."),
    as_json: bool = _json_option(),
) -> None:
    """List one carrier's rates."""
    results = _read(
        lambda m: m.rates.for_carrier(
            guid, org_port=origin, dest_port=destination, method=method
        )
    )
    _emit(results, "rate(s)", _rate_row, as_json)


if __name__ == "__main__":
    app()
