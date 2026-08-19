"""Command-line entry point.

Read-only capabilities that work end to end today: listing shipments for a date
range and listing entities.

    magaya shipments --from 2025-01-01 --to 2025-01-31
    magaya shipments --from 2025-01-01 --to 2025-01-31 --max 100 --json
    magaya entities
    magaya entities MUE --type client --json
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


@app.callback()
def main() -> None:
    """Magaya toolkit CLI. Run a subcommand (e.g. `shipments` or `entities`)."""


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


if __name__ == "__main__":
    app()
