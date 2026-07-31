# magaya-toolkit

A small, typed Python toolkit to **read data from the Magaya API** and **validate
Magaya XML** — without hand-writing SOAP envelopes or XML.

The Magaya API is an XML Web Service (SOAP over HTTPS). This toolkit wraps it
behind a clean, typed SDK so callers work with Python objects, not raw XML.

> **Scope today: read-only.** The toolkit reads transactions from Magaya and
> parses them into typed models. It does **not** create or modify anything in
> Magaya yet — see [Status](#status).

---

## Use as a library

The primary interface is the `Magaya` facade. It manages a single Magaya
session for you (one `StartSession` / `EndSession` per `with` block) and exposes
typed resources — you never touch access keys or pagination cookies:

```python
from magaya_toolkit import Magaya, MagayaSettings

with Magaya(MagayaSettings()) as magaya:
    shipments = magaya.shipments.list("2025-01-01", "2025-01-31")
    for s in shipments:
        print(s.number, s.mode, s.status)
```

`MagayaSettings()` reads your connection details from the environment / `.env`
(see [Configure](#configure)). Every resource call inside the same `with` block
reuses the one open session. Read resources return typed `Shipment` models.

The public API is exported from the package root: `Magaya`, `MagayaSettings`,
`Shipment`, `Measure`, and the errors `MagayaError`, `ApiError`,
`XmlValidationError`, `SessionError`.

---

## CLI

The `magaya` CLI is a thin client over the same core the library uses (the
`shipments` command drives the `Magaya` facade). Anything the CLI does, you can
do from Python via the facade.

- **List shipments by date range** — paginated, typed, as a table or JSON:
  ```bash
  magaya shipments --from 2025-01-01 --to 2025-01-31
  magaya shipments --from 2025-01-01 --to 2025-01-31 --max 100 --json
  ```
  Handles the Magaya pagination cursor correctly and merges Ocean and Air
  shipments into a single typed `Shipment` model.

- **Validate a Magaya XML file** — well-formedness, plus optional XSD:
  ```bash
  magaya validate path/to/transaction.xml
  magaya validate path/to/transaction.xml --xsd schemas/Shipment.xsd
  ```

## Status

| Capability | Status |
| --- | --- |
| Session handling (`StartSession` / `EndSession`) | ✅ working |
| Read shipments by date range (`GetFirst`/`GetNextTransbyDate`) | ✅ working, validated live |
| Typed `Shipment` read model + XML parser | ✅ working |
| CLI (`magaya shipments`, `magaya validate`) | ✅ working |
| XML validation (well-formedness + optional XSD) | ✅ working |
| Read other transaction types (invoices, entities, rates…) | ⏳ not yet — same pattern |
| Populate `schemas/` with the official Magaya XSDs | ⏳ pending |
| **Create / update** transactions (`SetTransaction`) | 🚫 out of scope for now |

---

## Requirements

- **Python 3.12+**
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- Network access to your Magaya Communication Server, and a Magaya **employee
  account with API access** (one dedicated API user per integration is the
  Magaya-recommended practice).

## Install

```bash
git clone git@github.com:mrz1m3rm4n/magaya-toolkit.git
cd magaya-toolkit
uv sync            # create the venv and install dependencies from the lockfile
```

## Configure

Copy the example env file and fill in your own Magaya connection details:

```bash
cp .env.example .env
```

```dotenv
# .env  — never commit this file (it is gitignored)
MAGAYA_API_URL=https://<COMPANY_ID>.magayacloud.com/api/Invoke?Handler=CSSoapService
MAGAYA_USERNAME=<your-api-username>
MAGAYA_PASSWORD=<your-api-password>
```

- For **Magaya cloud** installs, the endpoint is
  `https://<COMPANY_ID>.magayacloud.com/api/Invoke?Handler=CSSoapService`.
- For **on-premise** installs, it is usually
  `http://<SERVER>:3691/Invoke?Handler=CSSoapService` (default port `3691`).

> 🔒 **Security:** `.env` holds a plaintext API password. It is gitignored and
> must never be committed. Rotate credentials if they are ever shared or leaked.

## Usage

```bash
# List shipments as a table (Number, Mode, Direction, Status, Shipper -> Consignee, ETA)
uv run magaya shipments --from 2025-01-01 --to 2025-01-31

# As JSON, capped to the 100 most recent
uv run magaya shipments --from 2025-01-01 --to 2025-01-31 --max 100 --backwards --json

# Validate a Magaya XML file against an XSD
uv run magaya validate transaction.xml --xsd schemas/Shipment.xsd
```

`magaya shipments` options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--from` / `--to` | *(required)* | Date range, `yyyy-MM-dd`. Compared against the transaction date, not its creation date. |
| `--type` | `SH` | Magaya transaction type code (`SH` = shipments). |
| `--record-quantity` | `5` | Records fetched per API batch. Keep small for large transactions. |
| `--max` | *(none)* | Cap the total number of shipments returned. |
| `--json` | off | Emit a JSON array instead of the table. |
| `--backwards` / `--no-backwards` | off | Return the most recent transactions first. |

## Architecture (hexagonal)

```
src/magaya_toolkit/
├── __init__.py        # public SDK surface (Magaya, MagayaSettings, Shipment, errors…)
├── facade.py          # Magaya — SDK front door; owns one managed session
├── resources.py       # ShipmentsResource — typed reads over the facade session
├── domain/            # pure models + errors (no SOAP, no XML libs)
│   ├── shipment.py    #   Shipment read model + Measure
│   └── errors.py      #   MagayaError, ApiError, XmlValidationError, SessionError
├── application/       # ports (Protocols) + use cases — the boundaries
│   ├── ports.py       #   MagayaReader, ShipmentParser, XmlValidator
│   └── use_cases.py   #   list_shipments(...), collect_shipments(...)
└── infrastructure/    # adapters that implement the ports
    ├── config.py      #   MagayaSettings (.env)
    ├── soap/          #   MagayaSoapClient (httpx, hand-built SOAP 1.1)
    └── xml/           #   LxmlShipmentParser, LxmlValidator
```

Dependencies point inward: `infrastructure` depends on `application`/`domain`,
never the reverse. The SOAP client and the XML parser can be swapped without
touching business logic.

## Development

```bash
uv run pytest        # run the test suite (network-free — no live API calls)
uv run ruff check    # lint
```

Tests use `httpx.MockTransport` and canned SOAP responses, so they never touch
the real Magaya API.

---

## Magaya API notes

Useful facts about the Magaya API, verified against a live cloud instance:

- **Transport.** SOAP 1.1 over HTTPS `POST`, `Content-Type: text/xml`, method
  namespace `urn:CSSoapService`. No WSDL is required — the toolkit builds the
  envelopes by hand. No `SOAPAction` header is needed.
- **Session.** `StartSession(user, pass)` returns an integer `access_key` used
  by every subsequent call; always close with `EndSession(access_key)`. Only one
  session per key/IP is allowed (`too_many_open_sessions` otherwise).
- **Reading by date.** `GetFirstTransbyDate` returns a **cookie** cursor (not the
  data). `GetNextTransbyDate(cookie)` returns the transaction XML **and an
  updated cookie** — you must thread that updated cookie into the next call, or
  you re-fetch the same page forever. Iterate until `more_results == 0`.
- **XML namespace.** Returned transactions are namespaced under
  `http://www.magaya.com/XMLSchema/V1`.
- **Official XSDs** (v11.5.1+, public): `https://schema.magaya.net/Core/V1/*.xsd`
  (`Shipment.xsd`, `Accounting.xsd`, `Order.xsd`, `common.xsd`, …).
- **Best practices** (from the Magaya API docs): one API user per integration;
  no parallel calls; exponential backoff on `Timeout`; prefer
  `GetFirst`/`GetNextTransbyDate` over large single-shot date ranges.

Full reference (login required): <https://dev.magaya.com/index.php/API>.
```
