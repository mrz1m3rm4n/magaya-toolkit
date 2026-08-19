"""httpx + lxml adapter for the read-only Magaya SOAP API.

This client speaks SOAP 1.1 by hand (no WSDL): it builds the exact envelopes
the Magaya XML Web Service expects and parses responses with lxml, reading
elements namespace-agnostically via `local-name()` XPath since responses are
namespaced under `urn:CSSoapService`.

Scope is strictly read-only: session management plus read methods — date-range
transaction reads (`GetFirst`/`GetNextTransbyDate`), entity reads, and the
single-transaction read (`GetTransaction`). No write/create operation lives here.

Implements the `MagayaReader` port.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Self
from xml.sax.saxutils import escape

import httpx
from lxml import etree

from magaya_toolkit.domain.errors import ApiError
from magaya_toolkit.infrastructure.config import MagayaSettings

# Namespace of the SOAP method calls (per the Magaya API reference).
_METHOD_NS = "urn:CSSoapService"

# Default network timeout. Magaya date-range reads can be slow; keep it generous.
_DEFAULT_TIMEOUT_SECONDS = 60.0

# The single non-error status code returned in the `<return>` element.
_NO_ERROR = "no_error"

_CONTENT_TYPE = "text/xml"


def _envelope(body_inner: str) -> str:
    """Wrap a method-call fragment in the SOAP 1.1 envelope Magaya expects."""
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        '<s:Body s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        f"{body_inner}"
        "</s:Body></s:Envelope>"
    )


class MagayaSoapClient:
    """Read-only Magaya SOAP client.

    Inject an `httpx.Client` for testing; otherwise one is created with a
    sensible timeout. The client is not closed automatically when injected.
    """

    def __init__(
        self,
        settings: MagayaSettings | None = None,
        *,
        api_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if settings is not None:
            api_url = api_url or settings.api_url
            username = username or settings.username
            password = password or settings.password
        if not api_url or username is None or password is None:
            raise ValueError(
                "MagayaSoapClient requires api_url, username and password "
                "(pass a MagayaSettings or the explicit arguments)."
            )
        self._api_url = api_url
        self._username = username
        self._password = password
        # Track ownership so `close()` only closes a client we created; an
        # injected client stays under the caller's control.
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS)

    def close(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _call(self, body_inner: str) -> etree._Element:
        """POST a method call and return the parsed response root.

        Raises `ApiError` on a SOAP Fault. Callers extract fields via
        `local-name()` XPath. The `<return>` error-code check is centralized
        in `_check_return`.
        """
        payload = _envelope(body_inner).encode("utf-8")
        response = self._http.post(
            self._api_url,
            content=payload,
            headers={"Content-Type": _CONTENT_TYPE},
        )
        response.raise_for_status()

        root = etree.fromstring(response.content)

        fault = root.xpath("//*[local-name()='faultstring']")
        if fault:
            message = (fault[0].text or "SOAP Fault").strip()
            raise ApiError(message)

        return root

    @staticmethod
    def _text(root: etree._Element, local_name: str) -> str | None:
        """Return the text of the first element matching `local_name`, or None."""
        nodes = root.xpath("//*[local-name()=$name]", name=local_name)
        if not nodes:
            return None
        return nodes[0].text

    @classmethod
    def _check_return(cls, root: etree._Element) -> None:
        """Raise `ApiError` if the `<return>` status code is not `no_error`."""
        code = cls._text(root, "return")
        if code is not None and code != _NO_ERROR:
            raise ApiError(f"Magaya API error: {code}")

    # -- session -----------------------------------------------------------

    def start_session(self) -> int:
        body = (
            f'<q1:StartSession xmlns:q1="{_METHOD_NS}">'
            f'<user xsi:type="xsd:string">{escape(self._username)}</user>'
            f'<pass xsi:type="xsd:string">{escape(self._password)}</pass>'
            "</q1:StartSession>"
        )
        root = self._call(body)
        self._check_return(root)
        access_key = self._text(root, "access_key")
        if access_key is None:
            raise ApiError("Magaya API error: missing access_key in StartSession response")
        return int(access_key)

    def end_session(self, access_key: int) -> None:
        body = (
            f'<q1:EndSession xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            "</q1:EndSession>"
        )
        root = self._call(body)
        self._check_return(root)

    # -- date-range reads --------------------------------------------------

    def get_first_trans_by_date(
        self,
        access_key: int,
        trans_type: str,
        start_date: str,
        end_date: str,
        record_quantity: int,
        backwards_order: bool = False,
        flags: int = 0,
    ) -> tuple[str, bool]:
        # `backwards_order` MUST be sent as xsd:int (0/1); xsd:boolean is rejected.
        body = (
            f'<q1:GetFirstTransbyDate xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<type xsi:type="xsd:string">{escape(trans_type)}</type>'
            f'<start_date xsi:type="xsd:string">{escape(start_date)}</start_date>'
            f'<end_date xsi:type="xsd:string">{escape(end_date)}</end_date>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<record_quantity xsi:type="xsd:int">{int(record_quantity)}</record_quantity>'
            f'<backwards_order xsi:type="xsd:int">{1 if backwards_order else 0}</backwards_order>'
            "</q1:GetFirstTransbyDate>"
        )
        root = self._call(body)
        self._check_return(root)
        cookie = self._text(root, "cookie") or ""
        more_results = self._more_results(root)
        return cookie, more_results

    def get_next_trans_by_date(self, cookie: str) -> tuple[str, str, bool]:
        body = (
            f'<q1:GetNextTransbyDate xmlns:q1="{_METHOD_NS}">'
            f'<cookie xsi:type="xsd:string">{escape(cookie)}</cookie>'
            "</q1:GetNextTransbyDate>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped trans_list_xml when reading .text.
        trans_list_xml = self._text(root, "trans_list_xml") or ""
        # The cookie is in/out: capture the updated one to thread into the next
        # call. Fall back to the current cookie if the response omits it.
        next_cookie = self._text(root, "cookie") or cookie
        more_results = self._more_results(root)
        return trans_list_xml, next_cookie, more_results

    # -- entity reads (session-scoped, single-call) ------------------------

    def get_entities(self, access_key: int, start_with: str = "", flags: int = 0) -> str:
        """Return the raw `entity_list_xml` for all entities within an OPEN session.

        Single-call read (no pagination cookie). `start_with` optionally filters
        by name prefix. Assumes the caller already holds a valid `access_key`.
        """
        body = (
            f'<q1:GetEntities xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<start_with xsi:type="xsd:string">{escape(start_with)}</start_with>'
            "</q1:GetEntities>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped entity_list_xml when reading .text.
        return self._text(root, "entity_list_xml") or ""

    def get_entities_of_type(
        self, access_key: int, start_with: str, entity_type: int, flags: int = 0
    ) -> str:
        """Return the raw `entity_list_xml` for entities of `entity_type`.

        Single-call read (no pagination cookie). `entity_type` is a Magaya
        bitmask code. Assumes the caller already holds a valid `access_key`.
        """
        body = (
            f'<q1:GetEntitiesOfType xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<start_with xsi:type="xsd:string">{escape(start_with)}</start_with>'
            f'<entity_type xsi:type="xsd:int">{int(entity_type)}</entity_type>'
            "</q1:GetEntitiesOfType>"
        )
        root = self._call(body)
        self._check_return(root)
        return self._text(root, "entity_list_xml") or ""

    def get_entity_contacts(self, access_key: int, entity_uuid: str, flags: int = 0) -> str:
        """Return the raw `contact_list_xml` for one entity within an OPEN session.

        Single-call read (no pagination cookie). Assumes the caller already
        holds a valid `access_key`.
        """
        body = (
            f'<q1:GetEntityContacts xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<entity_uuid xsi:type="xsd:string">{escape(entity_uuid)}</entity_uuid>'
            "</q1:GetEntityContacts>"
        )
        root = self._call(body)
        self._check_return(root)
        return self._text(root, "contact_list_xml") or ""

    # -- transaction reads (session-scoped, single-call) -------------------

    def get_transaction(
        self, access_key: int, trans_type: str, number: str, flags: int = 0
    ) -> str:
        """Return the raw `trans_xml` for one transaction within an OPEN session.

        Single-call read (no pagination cookie). `trans_type` is a Magaya
        transaction type code (e.g. "SH" for a shipment, "IN" for an invoice);
        `number` is the transaction number or GUID — for shipments it is the
        Bill of Lading (Ocean/Ground) or Waybill number (Air). Assumes the
        caller already holds a valid `access_key`.

        The SOAP parameter order (`access_key`, `type`, `flags`, `number`)
        mirrors the Magaya API reference for `GetTransaction`.
        """
        body = (
            f'<q1:GetTransaction xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<type xsi:type="xsd:string">{escape(trans_type)}</type>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<number xsi:type="xsd:string">{escape(number)}</number>'
            "</q1:GetTransaction>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped trans_xml when reading .text.
        return self._text(root, "trans_xml") or ""

    # -- related transaction reads (session-scoped, single-call) -----------

    def get_entity_transactions(
        self,
        access_key: int,
        entity_uuid: str,
        start_date: str,
        end_date: str,
        flags: int = 0,
    ) -> str:
        """Return the raw `acctrans_list_xml` of an entity's accounting transactions.

        All accounting transactions (invoices, bills, …) of one entity within a
        date range, as a `<GUIDItems>` document. Single-call read (no pagination
        cookie). Dates use the `"yyyy-MM-dd"` format (any time part is ignored).
        Assumes the caller already holds a valid `access_key`.

        The SOAP parameter order (`access_key`, `entity_uuid`, `flags`,
        `start_date`, `end_date`) mirrors the Magaya API reference for
        `GetEntityTransactions`.
        """
        body = (
            f'<q1:GetEntityTransactions xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<entity_uuid xsi:type="xsd:string">{escape(entity_uuid)}</entity_uuid>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<start_date xsi:type="xsd:string">{escape(start_date)}</start_date>'
            f'<end_date xsi:type="xsd:string">{escape(end_date)}</end_date>'
            "</q1:GetEntityTransactions>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped acctrans_list_xml when reading .text.
        return self._text(root, "acctrans_list_xml") or ""

    def get_accounting_transactions(
        self, access_key: int, trans_type: str, number: str, flags: int = 0
    ) -> str:
        """Return the raw `trans_xml` of accounting transactions for one operation.

        The accounting transactions (invoices, bills) related to an operations
        transaction — e.g. a shipment — identified by `trans_type` + `number`,
        as a `<GUIDItems>` document. Single-call read (no pagination cookie).
        Assumes the caller already holds a valid `access_key`.

        The SOAP parameter order (`access_key`, `type`, `flags`, `number`)
        mirrors the Magaya API reference for `GetAccountingTransactions`.
        """
        body = (
            f'<q1:GetAccountingTransactions xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<type xsi:type="xsd:string">{escape(trans_type)}</type>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<number xsi:type="xsd:string">{escape(number)}</number>'
            "</q1:GetAccountingTransactions>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped trans_xml when reading .text.
        return self._text(root, "trans_xml") or ""

    def get_related_transactions(
        self, access_key: int, trans_type: str, number: str, flags: int = 0
    ) -> str:
        """Return the raw `trans_xml` of transactions related to an accounting one.

        The transaction(s) related to an invoice/bill — e.g. the shipment it
        bills — identified by `trans_type` + `number`, as a `<GUIDItems>`
        document. Single-call read (no pagination cookie). Assumes the caller
        already holds a valid `access_key`.

        The SOAP parameter order (`access_key`, `type`, `flags`, `number`)
        mirrors the Magaya API reference for `GetRelatedTransactions`.
        """
        body = (
            f'<q1:GetRelatedTransactions xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<type xsi:type="xsd:string">{escape(trans_type)}</type>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            f'<number xsi:type="xsd:string">{escape(number)}</number>'
            "</q1:GetRelatedTransactions>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped trans_xml when reading .text.
        return self._text(root, "trans_xml") or ""

    # -- existence & status (session-scoped, single-call) ------------------

    def exists_transaction(self, access_key: int, trans_type: str, number: str) -> bool:
        """Return whether a transaction of `trans_type` with `number` exists.

        `ExistsTransaction` reports a missing transaction via the
        `transaction_not_found` return code (not a SOAP fault) together with an
        `exist_trans` flag of 0, so we treat that code as "does not exist"
        rather than an error. Any other non-`no_error` code still raises
        `ApiError`. Assumes the caller already holds a valid `access_key`.
        """
        body = (
            f'<q1:ExistsTransaction xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<type xsi:type="xsd:string">{escape(trans_type)}</type>'
            f'<number xsi:type="xsd:string">{escape(number)}</number>'
            "</q1:ExistsTransaction>"
        )
        root = self._call(body)
        code = self._text(root, "return")
        if code not in (None, _NO_ERROR, "transaction_not_found"):
            raise ApiError(f"Magaya API error: {code}")
        return (self._text(root, "exist_trans") or "").strip() == "1"

    def get_transaction_status(self, access_key: int, trans_type: str, number: str) -> str:
        """Return the status string of a transaction (`GetTransactionStatus`).

        A lightweight probe for just the status (e.g. "Delivered", "Open")
        without fetching the full transaction XML. Raises `ApiError` if Magaya
        has no such transaction. Assumes the caller already holds a valid
        `access_key`.
        """
        body = (
            f'<q1:GetTransactionStatus xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<type xsi:type="xsd:string">{escape(trans_type)}</type>'
            f'<number xsi:type="xsd:string">{escape(number)}</number>'
            "</q1:GetTransactionStatus>"
        )
        root = self._call(body)
        self._check_return(root)
        return self._text(root, "trans_status") or ""

    # -- transaction log (session-scoped, single-call) ---------------------

    def query_log(
        self,
        access_key: int,
        start_date: str,
        end_date: str,
        log_entry_type: int,
        trans_type: str,
        flags: int = 0,
    ) -> str:
        """Return the raw `trans_list_xml` of a transaction-log query (`QueryLog`).

        Reads the change log for one `trans_type` (e.g. "IN" for invoices) over a
        date range within an OPEN session, returning a `<GUIDItems>` document of
        matching transaction references. Single-call read (no pagination cookie).
        Assumes the caller already holds a valid `access_key`.

        Dates use the `"yyyy-MM-ddTHH:mm:ss"` format. `log_entry_type` is a
        bitmask of the log operations to include (Creation=0x01, Deletion=0x02,
        Edition=0x04, Cleanup=0x08). Wide date ranges time out — keep the window
        narrow.

        The SOAP parameter order (`access_key`, `start_date`, `end_date`,
        `log_entry_type`, `trans_type`, `flags`) mirrors the Magaya API
        reference for `QueryLog`.
        """
        body = (
            f'<q1:QueryLog xmlns:q1="{_METHOD_NS}">'
            f'<access_key xsi:type="xsd:int">{int(access_key)}</access_key>'
            f'<start_date xsi:type="xsd:string">{escape(start_date)}</start_date>'
            f'<end_date xsi:type="xsd:string">{escape(end_date)}</end_date>'
            f'<log_entry_type xsi:type="xsd:int">{int(log_entry_type)}</log_entry_type>'
            f'<trans_type xsi:type="xsd:string">{escape(trans_type)}</trans_type>'
            f'<flags xsi:type="xsd:int">{int(flags)}</flags>'
            "</q1:QueryLog>"
        )
        root = self._call(body)
        self._check_return(root)
        # lxml auto-unescapes the HTML-escaped trans_list_xml when reading .text.
        return self._text(root, "trans_list_xml") or ""

    @classmethod
    def _more_results(cls, root: etree._Element) -> bool:
        """Parse the `<more_results>` 1/0 flag into a bool."""
        raw = cls._text(root, "more_results")
        return raw is not None and raw.strip() == "1"

    # -- session-scoped iterator ------------------------------------------

    def iter_transactions_by_date(
        self,
        access_key: int,
        trans_type: str,
        start_date: str,
        end_date: str,
        record_quantity: int = 5,
        backwards_order: bool = False,
        flags: int = 0,
    ) -> Iterator[str]:
        """Yield each `trans_list_xml` batch for a date range within an OPEN session.

        Assumes the caller already holds a valid `access_key` (from
        `start_session`) and is responsible for closing the session. This method
        neither opens nor closes a session: it only runs the query and threads
        the pagination cookie. Use `read_transactions_by_date` for the
        session-managed convenience variant.
        """
        # GetFirst returns the cookie to feed the first GetNext. It carries
        # no transaction XML itself.
        cookie, more_results = self.get_first_trans_by_date(
            access_key=access_key,
            trans_type=trans_type,
            start_date=start_date,
            end_date=end_date,
            record_quantity=record_quantity,
            backwards_order=backwards_order,
            flags=flags,
        )
        while more_results:
            # Thread the updated cookie back in; reusing the GetFirst cookie
            # would loop over the same page forever.
            trans_list_xml, cookie, more_results = self.get_next_trans_by_date(cookie)
            yield trans_list_xml

    # -- convenience iterator ---------------------------------------------

    def read_transactions_by_date(
        self,
        trans_type: str,
        start_date: str,
        end_date: str,
        record_quantity: int = 5,
        backwards_order: bool = False,
        flags: int = 0,
    ) -> Iterator[str]:
        """Yield each `trans_list_xml` batch for a date range.

        Opens a session, runs the query, and iterates `GetNext` until there are
        no more results. Always closes the session (Magaya best practice: do
        not leave sessions open and do not run them in parallel).
        """
        access_key = self.start_session()
        try:
            yield from self.iter_transactions_by_date(
                access_key=access_key,
                trans_type=trans_type,
                start_date=start_date,
                end_date=end_date,
                record_quantity=record_quantity,
                backwards_order=backwards_order,
                flags=flags,
            )
        finally:
            self.end_session(access_key)
