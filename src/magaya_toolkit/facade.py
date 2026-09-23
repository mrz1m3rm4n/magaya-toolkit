"""The `Magaya` SDK facade: the read-only toolkit's front door.

`Magaya` manages exactly one Magaya session and exposes typed resource
namespaces (`shipments`, and more to come) that read through it. Callers never
touch the access key or pagination cookies — the facade owns the session
lifecycle and the resources reuse it.

Read-only: the facade exposes read resources only; no write/create path exists.
"""

from __future__ import annotations

from typing import Self

from magaya_toolkit.domain.errors import SessionError
from magaya_toolkit.infrastructure.config import MagayaSettings
from magaya_toolkit.infrastructure.soap.magaya_client import MagayaSoapClient
from magaya_toolkit.resources import (
    CatalogResource,
    EntitiesResource,
    FilesResource,
    InventoryResource,
    InvoicesResource,
    RatesResource,
    ShipmentsResource,
    TrackingResource,
)


class Magaya:
    """SDK entry point. Manages ONE Magaya session and exposes typed resources.

    Usage:
        with Magaya(settings) as magaya:
            shipments = magaya.shipments.list("2025-01-01", "2025-01-31")

    Multiple resource calls inside a single `with` block reuse the same session
    (exactly one `StartSession`). `EndSession` is opt-in and off by default:
    Magaya returns the same `access_key` for a given credential every time, so
    the key is a constant of the credential rather than a per-session token —
    ending it tears down the one session shared by every other consumer of
    that credential (e.g. a production ETL), not just this process. Pass
    `end_session_on_close=True` if this process should own the shared session
    and is safe to end it. `open()` is idempotent and `close()` is safe to
    call when no session is open or twice.

    Pass a `MagayaSoapClient` via `client=` only to inject a test double; in
    normal use a client is built from `settings`.
    """

    def __init__(
        self,
        settings: MagayaSettings | None = None,
        *,
        client: MagayaSoapClient | None = None,
        end_session_on_close: bool = False,
    ) -> None:
        if client is None:
            client = MagayaSoapClient(settings or MagayaSettings())
        self._client = client
        self._access_key: int | None = None
        self._end_session_on_close = end_session_on_close

        # Resource namespaces bound to this facade. Add more the same way.
        self.shipments = ShipmentsResource(self)
        self.entities = EntitiesResource(self)
        self.invoices = InvoicesResource(self)
        self.catalog = CatalogResource(self)
        self.rates = RatesResource(self)
        self.files = FilesResource(self)
        self.inventory = InventoryResource(self)
        self.tracking = TrackingResource(self)

    # -- session lifecycle -------------------------------------------------

    def open(self) -> Self:
        """Open a session if one is not already open. Idempotent; returns self."""
        if self._access_key is None:
            self._access_key = self._client.start_session()
        return self

    def close(self) -> None:
        """Close the client and, if opted in, end the session. Safe to call twice.

        `EndSession` is only sent when `end_session_on_close=True` was passed
        to `__init__` — the access key is shared across every process using
        this credential, so ending it by default would strand them mid-batch.
        """
        if self._access_key is not None:
            try:
                if self._end_session_on_close:
                    self._client.end_session(self._access_key)
            finally:
                self._access_key = None
        self._client.close()

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- accessors ---------------------------------------------------------

    @property
    def client(self) -> MagayaSoapClient:
        """The underlying SOAP client. For resources; not part of the SDK contract."""
        return self._client

    @property
    def access_key(self) -> int:
        """The open session's access key.

        Raises `SessionError` if the session is not open — callers should never
        need this directly; resources read it to reuse the managed session.
        """
        if self._access_key is None:
            raise SessionError(
                "Session not open — use `with Magaya(...) as m:` or call m.open()"
            )
        return self._access_key
