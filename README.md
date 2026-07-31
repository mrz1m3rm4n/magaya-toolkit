# magaya-toolkit

Python toolkit to **build Magaya transactions** (references, invoices, and more)
and **validate their XML structure** before submitting them through the Magaya API.

The Magaya API is an XML Web Service that uses SOAP over HTTP. This toolkit wraps
it behind clean, typed use cases so callers don't hand-write XML or SOAP envelopes.

## Goals

1. Build transactions from typed domain models (references, invoices, charges).
2. Validate the resulting XML against the Magaya Transactions format before sending.
3. Submit transactions through the Magaya SOAP API.

## Architecture (hexagonal)

```
src/magaya_toolkit/
├── domain/            # pure models + errors (no SOAP, no XML libs)
├── application/       # use cases + ports (Protocols) — the boundaries
└── infrastructure/    # adapters that implement the ports
    ├── xml/           # lxml validator  (WORKING)
    └── soap/          # zeep Magaya API client (SCAFFOLD — pending WSDL wiring)
```

Dependencies point inward: infrastructure depends on application/domain, never
the reverse. Swap the SOAP client or the XML validator without touching business logic.

## Status

- ✅ XML validation (well-formedness + optional XSD) — `magaya validate <file>`
- ⏳ Domain models for reference/invoice — sketched, fields to be mapped
- ⏳ SOAP client — scaffolded, needs the WSDL URL and auth flow

## Setup

```bash
uv sync           # create venv + install deps from the lockfile
uv run pytest     # run the tests
uv run magaya validate path/to/transaction.xml
uv run magaya validate path/to/transaction.xml --xsd schemas/magaya.xsd
```

## Magaya API reference (from the Hyperion dev wiki)

Source: `https://dev.magaya.com/index.php/API` (login required).

**Session:** `StartSession`, `EndSession`
**Transactions:** `GetTransaction`, `SetTransaction`, `DeleteTransaction`,
`GetTransRangeByDate`, `ExistsTransaction`, `RenameTransaction`,
`GetRelatedTransactions`, `GetTransactionStatus`
**Entities:** `SetEntity`, `GetEntities`, `GetEntitiesOfType`, `GetEntityContacts`
**Orders / Shipments:** `SubmitSalesOrder`, `SubmitShipment`, `SubmitPickupOrder`,
`SubmitCargoRelease`, `UpdateOrder`, `ApproveOrder`, `CancelSalesOrder`
**Rates / Charges:** `GetStandardRates`, `GetClientRates`, `GetCarrierRates`,
`SetRate`, `SetTransactionCharges`
**Attachments:** `SetAttachment`, `GetAttachment`, `GetAllAttachments`
**Other:** `QueryLog`, `Invoke`, `GetPODData`, `UpdatePOD`, `GetWebDocument`,
`SetCustomFieldValue`

See also: Error Codes, Transaction Flags, and the Magaya Transactions XML format.

## Configuration

Copy `.env.example` to `.env` and fill in the Magaya connection details. Never
commit `.env`.
