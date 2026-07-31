"""Command-line entry point.

Currently exposes the one capability that already works end to end: validating
a Magaya XML file. Building references/invoices and submitting them will be
added as their use cases land.

    magaya validate path/to/transaction.xml
    magaya validate path/to/transaction.xml --xsd schemas/magaya.xsd
"""

from __future__ import annotations

from pathlib import Path

import typer

from magaya_toolkit.domain.errors import XmlValidationError
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


if __name__ == "__main__":
    app()
