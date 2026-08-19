"""Domain read model for a Magaya transaction reference.

Pure, in-memory representation of one `<GUIDItem>` returned by `QueryLog`. It
knows nothing about SOAP or XML — an infrastructure adapter turns the Magaya
XML into these objects.

Read-only: this model is only ever populated from data the API returns; the
toolkit never writes transactions. Only `guid` and `type` are required; the log
metadata defaults to None so that items that omit a field never cause an error.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = ["TransactionRef"]


class TransactionRef(BaseModel):
    """A lightweight reference to a Magaya transaction, as returned by `QueryLog`.

    Each `<GUIDItem>` in a `QueryLog` result becomes one `TransactionRef`. It is
    only a pointer plus its log metadata — fetch the full transaction with
    `GetTransaction` (e.g. `Magaya.invoices.get(...)`).
    """

    guid: str
    type: str
    log_type: str | None = None
    log_date: datetime | None = None
