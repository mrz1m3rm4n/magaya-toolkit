"""Command-line entry point.

Read-only capabilities that work end to end today: validating a Magaya XML file
and listing shipments for a date range.

    magaya validate path/to/transaction.xml
    magaya validate path/to/transaction.xml --xsd schemas/magaya.xsd
    magaya shipments --from 2025-01-01 --to 2025-01-31
    magaya shipments --from 2025-01-01 --to 2025-01-31 --max 100 --json
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from magaya_toolkit.domain.errors import ApiError, XmlValidationError
from magaya_toolkit.facade import Magaya
from magaya_toolkit.infrastructure.config import MagayaSettings
from magaya_toolkit.infrastructure.xml.lxml_validator import LxmlValidator

app = typer.Typer(help="Build and validate Magaya API transactions.")


@app.callback()
def main() -> None:
    """Magaya toolkit CLI. Run a subcommand (e.g. `validate`)."""


@app.command()
def validate(
    xml_file: Path = typer.Argument(..., exists=True, readable=True),
    xsd: Path = typer.Option(None, "--xsd", help="Optional XSD schema to validate against."),
) -> None:
    """Validate an XML file (well-formedness, plus schema if --xsd is given)."""
    validator = LxmlValidator(xsd_path=xsd)
    try:
        validator.validate(xml_file.read_bytes())
    except XmlValidationError as exc:
        typer.secho(f"INVALID: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"OK: {xml_file} is valid.", fg=typer.colors.GREEN)


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


if __name__ == "__main__":
    app()
