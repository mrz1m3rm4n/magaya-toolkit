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
from pathlib import Path

import typer
from pydantic import ValidationError

from magaya_toolkit.domain.entity import EntityType
from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.facade import Magaya
from magaya_toolkit.infrastructure.config import (
    MagayaSettings,
    candidate_env_files,
)

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
invoices_app = typer.Typer(help="Read invoices.")
files_app = typer.Typer(help="Read the files attached to a transaction.")
inventory_app = typer.Typer(help="Read warehouse inventory.")
tracking_app = typer.Typer(help="Read a transaction as one of your LiveTrack clients.")
app.add_typer(catalog_app, name="catalog")
app.add_typer(rates_app, name="rates")
app.add_typer(invoices_app, name="invoices")
app.add_typer(files_app, name="files")
app.add_typer(inventory_app, name="inventory")
app.add_typer(tracking_app, name="tracking")


@app.callback()
def main() -> None:
    """Magaya toolkit CLI. Run a subcommand (e.g. `shipments` or `catalog`)."""


def _settings() -> MagayaSettings:
    """Load settings, explaining where `.env` was looked for when they are missing."""
    try:
        return MagayaSettings()
    except ValidationError as exc:
        missing = sorted(
            str(error["loc"][0]) for error in exc.errors() if error["type"] == "missing"
        )
        typer.secho(
            "ERROR: missing Magaya connection settings: "
            + ", ".join(f"MAGAYA_{name.upper()}" for name in missing),
            fg=typer.colors.RED,
            err=True,
        )
        # The walk up to the filesystem root can be long; show the near ones and
        # the user-level file, which are the two places anyone actually puts it.
        searched = [str(path) for path in candidate_env_files()]
        # Keep the nearest directories and the user-level file; elide the middle
        # of a long walk rather than printing every parent up to "/".
        shown = searched if len(searched) <= 4 else searched[:2] + ["..."] + searched[-2:]
        typer.secho(
            "Set them in the environment, or put a .env in one of:\n  "
            + "\n  ".join(shown)
            + "\nMAGAYA_ENV_FILE=/path/to/.env overrides the search.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=1) from exc


def _read(read):
    """Run `read(magaya)` in a managed session, reporting `ApiError` cleanly."""
    settings = _settings()
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
    settings = _settings()
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

    settings = _settings()
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


# -- invoices --------------------------------------------------------------


@invoices_app.command("query")
def invoices_query(
    from_date: str = typer.Option(..., "--from", help="Start (yyyy-MM-ddTHH:mm:ss)."),
    to_date: str = typer.Option(..., "--to", help="End (yyyy-MM-ddTHH:mm:ss)."),
    log_entry_type: int = typer.Option(
        1, "--log-type", help="Log bitmask: 1 Creation, 2 Deletion, 4 Edition, -1 any."
    ),
    as_json: bool = _json_option(),
) -> None:
    """List invoice references from the transaction log. Keep the window narrow."""
    results = _read(
        lambda m: m.invoices.query(from_date, to_date, log_entry_type=log_entry_type)
    )
    _emit(
        results,
        "invoice ref(s)",
        lambda r: f"{r.guid}\t{r.type or '-'}\t{r.log_type or '-'}\t{r.log_date or '-'}",
        as_json,
    )


@invoices_app.command("get")
def invoices_get(
    number: str = typer.Argument(..., help="Invoice number or GUID."),
    as_json: bool = _json_option(),
) -> None:
    """Fetch one invoice by number or GUID."""
    invoice = _read(lambda m: m.invoices.get(number))
    _emit([invoice], "invoice(s)", _invoice_row, as_json)


@invoices_app.command("range")
def invoices_range(
    from_date: str = typer.Option(..., "--from", help="Start date (yyyy-MM-dd)."),
    to_date: str = typer.Option(..., "--to", help="End date (yyyy-MM-dd)."),
    js_function: str = typer.Option(
        "", "--js-function", help="Name of a JavaScript filter defined in Magaya."
    ),
    js_param: list[str] = typer.Option(
        [], "--js-param", help="Filter argument, repeatable, in declaration order."
    ),
    as_json: bool = _json_option(),
) -> None:
    """Read a whole date range of full invoices in one call.

    Heavy: a single day can run to tens of megabytes. Use --js-function to make
    Magaya filter before anything crosses the network.
    """
    results = _read(
        lambda m: m.invoices.range(
            from_date, to_date, js_function=js_function, js_params=js_param
        )
    )
    _emit(results, "invoice(s)", _invoice_row, as_json)


def _invoice_row(invoice) -> str:
    return (
        f"{invoice.number or '-'}\t"
        f"{invoice.status or '-'}\t"
        f"{invoice.total_amount if invoice.total_amount is not None else '-'}\t"
        f"{invoice.currency or '-'}\t"
        f"{invoice.entity_name or '-'}"
    )


# -- files -----------------------------------------------------------------


@files_app.command("attachments")
def files_attachments(
    trans_type: str = typer.Argument(..., help="Transaction type, e.g. IN or SH."),
    number: str = typer.Argument(..., help="Transaction number or GUID."),
    as_json: bool = _json_option(),
) -> None:
    """List the attachments on one transaction."""
    results = _read(lambda m: m.files.attachments(trans_type, number))
    _emit(
        results,
        "attachment(s)",
        lambda a: (
            f"{a.identifier or '-'}\t"
            f"{a.name or '-'}.{a.extension or '-'}\t"
            f"{a.size if a.size is not None else '-'}\t"
            f"{'image' if a.is_image else ''}"
        ),
        as_json,
    )


@files_app.command("get-attachment")
def files_get_attachment(
    trans_type: str = typer.Argument(..., help="Transaction type, e.g. IN or SH."),
    number: str = typer.Argument(..., help="Transaction number or GUID."),
    identifier: str = typer.Argument(..., help="Attachment identifier, from `attachments`."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Where to write the file."),
) -> None:
    """Download one attachment to disk."""

    def read(magaya):
        refs = magaya.files.attachments(trans_type, number)
        match = next((r for r in refs if r.identifier == identifier), None)
        if match is None:
            available = ", ".join(r.identifier or "?" for r in refs) or "none"
            typer.secho(
                f"ERROR: no attachment {identifier!r} on {trans_type} {number}. "
                f"Available: {available}.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        return magaya.files.attachment(match), match

    attachment, ref = _read(read)
    _write_file(attachment.data, out or Path(attachment.suggested_filename()))
    if attachment.size_matches is False:
        typer.secho(
            f"WARNING: Magaya reported {ref.size} bytes but {len(attachment.data or b'')} "
            "arrived — the transfer looks truncated.",
            fg=typer.colors.YELLOW,
            err=True,
        )


@files_app.command("documents")
def files_documents(
    trans_type: str = typer.Argument(..., help="Transaction type, e.g. SH."),
    number: str = typer.Argument(..., help="Transaction number or GUID."),
    as_json: bool = _json_option(),
) -> None:
    """List the Magaya-generated documents on one transaction."""
    results = _read(lambda m: m.files.documents(trans_type, number))
    _emit(
        results,
        "document(s)",
        lambda d: (
            f"{d.identifier or '-'}\t"
            f"{d.name or '-'}\t"
            f"stored as .{d.extension or '?'}\t"
            f"{'magaya' if d.is_magaya_doc else ''}"
        ),
        as_json,
    )


@files_app.command("get-document")
def files_get_document(
    trans_type: str = typer.Argument(..., help="Transaction type, e.g. SH."),
    number: str = typer.Argument(..., help="Transaction number or GUID."),
    identifier: str = typer.Argument(..., help="Document identifier, from `documents`."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Where to write the PDF."),
) -> None:
    """Download one document, rendered to PDF."""

    def read(magaya):
        docs = magaya.files.documents(trans_type, number)
        match = next((d for d in docs if d.identifier == identifier), None)
        if match is None:
            available = ", ".join(d.identifier or "?" for d in docs) or "none"
            typer.secho(
                f"ERROR: no document {identifier!r} on {trans_type} {number}. "
                f"Available: {available}.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        return magaya.files.document(match), match

    document, ref = _read(read)
    # Magaya renders every document to PDF, whatever it stores it as.
    _write_file(document.data, out or Path(f"{ref.name or ref.identifier}.pdf"))


def _write_file(data: bytes | None, path: Path) -> None:
    """Write downloaded bytes, refusing to pretend an empty response is a file."""
    if not data:
        typer.secho("ERROR: Magaya returned no content.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    path.write_bytes(data)
    typer.echo(f"{path} ({len(data)} bytes)")


# -- inventory -------------------------------------------------------------


@inventory_app.command("definitions")
def inventory_definitions(
    client: str = typer.Option("", "--client", help="Scope to one customer's definitions."),
    stocked: bool = typer.Option(
        False, "--stocked", help="Only the definitions that actually hold pieces."
    ),
    as_json: bool = _json_option(),
) -> None:
    """List item definitions. Without --client this is a large response."""
    results = _read(lambda m: m.inventory.definitions(client))
    if stocked:
        results = [d for d in results if d.pieces]
    _emit(
        results,
        "definition(s)",
        lambda d: (
            f"{d.part_number or '-'}\t"
            f"{d.description or '-'}\t"
            f"{d.pieces if d.pieces is not None else '-'}\t"
            f"{d.item_type or '-'}\t"
            f"{d.guid or '-'}"
        ),
        as_json,
    )


@inventory_app.command("items")
def inventory_items(
    definition_guid: str = typer.Argument(..., help="Item definition GUID."),
    as_json: bool = _json_option(),
) -> None:
    """List the physical pieces on hand for one item definition."""
    results = _read(lambda m: m.inventory.items(definition_guid))
    _emit(
        results,
        "item(s)",
        lambda i: (
            f"{i.serial_number or '-'}\t"
            f"{i.status or '-'}\t"
            f"{i.location.code if i.location else '-'}\t"
            f"{'moved' if i.moved else ''}\t"
            f"{i.warehouse_receipt_number or '-'}"
        ),
        as_json,
    )


@inventory_app.command("vin")
def inventory_vin(
    vin: str = typer.Argument(..., help="Vehicle VIN."),
    as_json: bool = _json_option(),
) -> None:
    """Look one vehicle up by VIN."""
    item = _read(lambda m: m.inventory.item_from_vin(vin))
    _emit(
        [item],
        "item(s)",
        lambda i: f"{i.serial_number or '-'}\t{i.description or '-'}\t{i.status or '-'}",
        as_json,
    )


# -- tracking --------------------------------------------------------------


def _livetrack_password() -> str:
    """Prompt for the client's password rather than take it as an argument.

    A password passed on the command line lands in shell history and in the
    process list. This one belongs to your customer, so it is prompted for, or
    read from MAGAYA_LIVETRACK_PASSWORD when a script needs it.
    """
    return typer.Option(
        ...,
        "--password",
        prompt="LiveTrack client password",
        hide_input=True,
        envvar="MAGAYA_LIVETRACK_PASSWORD",
        help="Prompted for if omitted; also read from MAGAYA_LIVETRACK_PASSWORD.",
    )


@tracking_app.command("shipment")
def tracking_shipment(
    user: str = typer.Argument(..., help="LiveTrack client name."),
    guid: str = typer.Argument(..., help="Shipment GUID."),
    password: str = _livetrack_password(),
    as_json: bool = _json_option(),
) -> None:
    """Read one shipment as that LiveTrack client sees it."""
    shipment = _read(lambda m: m.tracking.shipment(user, password, guid))
    _emit(
        [shipment],
        "shipment(s)",
        lambda s: f"{s.number}\t{s.mode}\t{s.status or '-'}\tETA={_eta(s)}",
        as_json,
    )


@tracking_app.command("invoice")
def tracking_invoice(
    user: str = typer.Argument(..., help="LiveTrack client name."),
    guid: str = typer.Argument(..., help="Invoice GUID."),
    password: str = _livetrack_password(),
    as_json: bool = _json_option(),
) -> None:
    """Read one invoice as that LiveTrack client sees it."""
    invoice = _read(lambda m: m.tracking.invoice(user, password, guid))
    _emit([invoice], "invoice(s)", _invoice_row, as_json)


if __name__ == "__main__":
    app()
