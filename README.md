# magaya-toolkit

A small, typed Python toolkit to **read data from the Magaya API** — without
hand-writing SOAP envelopes or parsing XML.

The Magaya API is an XML Web Service (SOAP over HTTPS). This toolkit wraps it
behind a clean, typed SDK so callers work with Python objects, not raw XML.

> **Scope today: read-only.** The toolkit reads transactions from Magaya and
> parses them into typed models. It does **not** create or modify anything in
> Magaya yet — see [Status](#status).

---

## Use as a library

The primary interface is the `Magaya` facade. It manages a single Magaya
session for you (one `StartSession` per `with` block; `EndSession` is opt-in
and off by default — see [Magaya API notes](#magaya-api-notes)) and exposes
typed resources — you never touch access keys or pagination cookies:

```python
from magaya_toolkit import EntityType, Magaya, MagayaSettings

with Magaya(MagayaSettings()) as magaya:
    shipments = magaya.shipments.list("2025-01-01", "2025-01-31")
    for s in shipments:
        print(s.number, s.mode, s.status)

    # Read entities (Client, Carrier, Vendor, …) and their contacts:
    entities = magaya.entities.find("MUE", entity_type=EntityType.CLIENT)
    for e in entities:
        print(e.name, e.kind, e.entity_id)
    contacts = magaya.entities.contacts(entities[0].guid)
```

`magaya.entities.find(start_with="", *, entity_type=None, flags=0)` returns typed
`Entity` models. Pass an `EntityType` (or omit it for all entities); with a type
it reads `GetEntitiesOfType`, otherwise `GetEntities`.
`magaya.entities.contacts(entity_guid)` returns typed `EntityContact` models for
one entity.

> **Client vs. Customer:** Magaya's API names the client entity type `Customer`
> (code `0x002`) but returns `<Client>` elements. This SDK uses the descriptive
> label users recognize — `EntityType.CLIENT` and `--type client` — and keeps
> `EntityType.CUSTOMER` / `--type customer` as aliases. Returned clients have
> `kind == "Client"`. The other type names (`carrier`, `vendor`, …) already match
> Magaya's data, so no aliasing is needed there.

`MagayaSettings()` reads your connection details from the environment / `.env`
(see [Configure](#configure)). Every resource call inside the same `with` block
reuses the one open session. Read resources return typed models.

### Catalogs — `magaya.catalog`

The reference data your install is configured with. These turn codes that other
resources hand back as opaque strings into something with meaning: an invoice's
currency, a charge line's code, a shipment event's name, a port code.

```python
with Magaya() as magaya:
    for c in magaya.catalog.currencies():
        print(c.code, c.name, c.exchange_rate, c.is_home_currency)

    charges = magaya.catalog.charges()          # items & services
    by_code = {c.code: c.description for c in charges}

    for p in magaya.catalog.ports():
        # A port can serve several modes — or none.
        print(f"{p.country_code}{p.code}", p.name, p.methods)
```

Also available: `accounts()` (the chart of accounts, with each account's parent
nested), `events()` (the tracking events this install can stamp) and
`client_charges(client_guid)` (one client's overrides).

Exchange rates are `Decimal`, at Magaya's full precision — it sends rates like
`0.05069297294009104254`, which `float` would quietly round.

`charges()` is heavy on a mature install (a few MB); read it once and keep it.

### Rates — `magaya.rates`

```python
with Magaya() as magaya:
    rates = magaya.rates.standard(method="Ocean")
    for r in rates:
        print(r.origin_country_code, "->", r.destination_country_code, r.prices)

    # A client's negotiated rates, plus the standard ones that apply to them:
    magaya.rates.for_client(client_guid, include_standard=True)
    magaya.rates.for_carrier(carrier_guid, org_port="MXZLO")
```

Ports in the lane filter use Magaya's `CountryCode + PortCode` form — `MXZLO` is
Manzanillo, Mexico. Pair `Port.country_code` with `Port.code` from
`catalog.ports()` to build one. A code that is not a working port raises
`ApiError`, it does not quietly return nothing.

Magaya prices a rate by `apply_by`: `Package`, `Weight`, `Volume`, `Pieces`,
`Formula` or `Unknown`. Only `Package` pricing is parsed today, into
`package_rates` — check `apply_by` before reading prices.

### Attachments and documents — `magaya.files`

Magaya keeps two kinds of file on a transaction and they travel different roads:
**attachments** are what people attached, **documents** are Magaya's own
generated paperwork. Neither ships inside a transaction read, so both are
deliberate two-step trips — list cheap pointers, then pay for the bytes of the
one you want.

```python
from pathlib import Path

with Magaya() as magaya:
    refs = magaya.files.attachments("IN", "F-78282")
    for ref in refs:
        print(ref.name, ref.extension, ref.size)   # decide before fetching

    attachment = magaya.files.attachment(refs[0])
    if attachment.size_matches:                    # catches a truncated transfer
        Path(attachment.suggested_filename()).write_bytes(attachment.data)

    docs = magaya.files.documents("SH", shipment_guid)
    pdf = magaya.files.document(docs[0])
    Path("bl.pdf").write_bytes(pdf.data)
```

`data` arrives already decoded from Base64. `document()` returns a PDF whatever
`DocumentRef.extension` says Magaya stores it as. Use `WebDocument.size` for the
real byte count — the API's own `encoded_length` measures the Base64 string, not
the file.

### Warehouse inventory — `magaya.inventory`

Two levels: a definition is what a thing **is**, an item is where a piece of it
**is**.

```python
with Magaya() as magaya:
    definitions = magaya.inventory.definitions()
    stocked = [d for d in definitions if d.pieces]      # skip the empty ones

    for item in magaya.inventory.items(stocked[0].guid):
        print(item.serial_number, item.status, item.location.code, item.moved)
```

`definitions()` with no customer returns the definitions belonging to no
customer, which on a stocked install is most of them and a heavy response.
`ItemDefinition.pieces` is how you tell which ones are worth calling `items()`
for.

### Batch reads and server-side filtering

`shipments.list` paginates and is what you normally want. `range()` reads a whole
date range in one unpaginated call — heavier by design, and a single day of
shipments can exceed the client timeout.

What makes the batch practical is `js_function`: the name of a boolean
JavaScript function you have defined in Magaya under **Configuration →
JavaScript Code**. Magaya evaluates it per transaction and only the matches
cross the network.

```python
with Magaya() as magaya:
    invoices = magaya.invoices.range("2026-07-01", "2026-07-02")

    # Filtered server-side; arguments go in the order the function declares them:
    magaya.shipments.list("2026-07-01", "2026-07-31",
                          js_function="GetTransactionByStatus",
                          js_params=["Loaded"])

    magaya.invoices.for_billing_client(client_guid, "2026-07-01", "2026-08-01")
```

`js_function` is available on `shipments.list`, `shipments.range`,
`invoices.range` and `invoices.query`. An unknown function name raises
`ApiError`. Note these are **not** JSON variants — `JS` is JavaScript.

### LiveTrack — `magaya.tracking`

The one resource that does not use the API session. It authenticates with a
LiveTrack **client's** own name and password — what your customer logs into the
tracking portal with — so it answers "what does this customer actually see?"
without trusting the answer to your wider API permissions.

```python
magaya = Magaya()          # no `with` needed: there is no session to open
shipment = magaya.tracking.shipment(client_user, client_password, shipment_guid)
magaya.close()
```

Wrong credentials, or a transaction that client may not see, raise `ApiError`.

### Exports

The public API is exported from the package root: `Magaya`, `MagayaSettings`,
the read models (`Shipment`, `Invoice`, `Entity`, `EntityContact`, `Currency`,
`AccountDefinition`, `ChargeDefinition`, `EventDefinition`, `Port`, `Rate`,
`Package`, `Attachment`, `AttachmentRef`, `DocumentRef`, `WebDocument`,
`ItemDefinition`, `InventoryItem`, `WarehouseLocation`, `TransactionRef`,
`Measure`, `Address`), the `EntityType` codes, the `ATTACH_DOCS_SUMMARY` flag,
and the errors `MagayaError`, `ApiError`, `XmlValidationError`, `SessionError`.

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

- **List entities** — Clients, Carriers, Vendors, …, as a table or JSON:
  ```bash
  magaya entities
  magaya entities MUE --type client --json
  ```
  Optional positional `START_WITH` filters by name prefix. `--type` accepts
  `client`, `carrier`, `vendor`, `forwarding-agent`, `warehouse-provider`,
  `employee`, `salesman`, or `division`; omit it for all entities. (`customer`
  is accepted as an alias of `client` — see the library note above.)

- **Read the catalogs** — currencies, chart of accounts, charges, events, ports:
  ```bash
  magaya catalog currencies
  magaya catalog ports --json
  magaya catalog accounts
  magaya catalog events
  magaya catalog charges                    # the global item/service list
  magaya catalog charges --client <GUID>    # one client's overrides
  ```
  `catalog ports` prints the port as the `CountryCode+PortCode` token the rate
  filters expect (`MXZLO`), so its first column pastes straight into a rate
  query.

- **Read rates** — standard, per client, per carrier:
  ```bash
  magaya rates standard --method Ocean
  magaya rates standard --origin MXZLO --destination USLAX
  magaya rates client <GUID> --include-standard
  magaya rates carrier <GUID> --origin MXZLO
  ```
  `--origin` / `--destination` take the `CountryCode+PortCode` form. A code that
  is not a working port exits non-zero with Magaya's `invalid_operation` rather
  than quietly returning nothing.

- **Read invoices** — log references, one invoice, or a whole range:
  ```bash
  magaya invoices query --from 2026-07-01T00:00:00 --to 2026-07-02T00:00:00
  magaya invoices get F-78394
  magaya invoices range --from 2026-07-01 --to 2026-07-02
  magaya invoices range --from 2026-07-01 --to 2026-07-31 \
      --js-function byDivision --js-param "DIV 1"
  ```
  `range` reads full invoices unpaginated and a single day can run to tens of
  megabytes; `--js-function` names a JavaScript filter defined in Magaya so the
  filtering happens before anything crosses the network. Repeat `--js-param`
  once per argument, in the order the function declares them.

- **Download attachments and documents**:
  ```bash
  magaya files attachments IN F-78282          # identifier is the first column
  magaya files get-attachment IN F-78282 144402385 -o invoice.xml

  magaya files documents SH <SHIPMENT_GUID>
  magaya files get-document SH <SHIPMENT_GUID> 144517945 -o bl.pdf
  ```
  An identifier that is not on that transaction exits non-zero and lists the
  ones that are. Documents always come back as PDF, whatever Magaya stores them
  as. If the bytes that arrive do not match the size Magaya reported, the
  download is still written but a warning says so.

- **Read warehouse inventory**:
  ```bash
  magaya inventory definitions --stocked      # skip the ones holding nothing
  magaya inventory items <DEFINITION_GUID>
  magaya inventory vin 1HGCM82633A004352
  ```
  `definitions` prints the GUID last, which is what `items` takes.

- **Read as one of your LiveTrack clients**:
  ```bash
  magaya tracking shipment acme-client <SHIPMENT_GUID>
  magaya tracking invoice acme-client <INVOICE_GUID>
  ```
  Answers "what does this customer actually see?" using their own portal
  credentials rather than your API user's wider permissions. The password is
  **prompted for**, never passed as an argument — a password in `argv` lands in
  shell history and in the process list. Scripts can set
  `MAGAYA_LIVETRACK_PASSWORD` instead.

Every command takes `--json` and prints a JSON array instead of the table, so
output pipes straight into `jq`. Decimals are serialized as strings, which is
what keeps an exchange rate's twenty significant digits intact.

## Status

| Capability | Status |
| --- | --- |
| Session handling (`StartSession` / `EndSession`) | ✅ working |
| Read shipments by date range (`GetFirst`/`GetNextTransbyDate`) | ✅ working, validated live |
| Typed `Shipment` read model + XML parser | ✅ working |
| Read one shipment by number/GUID (`GetTransaction`) | ✅ working, validated live |
| Read invoices (`QueryLog` refs + `GetTransaction`) | ✅ working, validated live |
| Related-transaction links (entity/shipment/invoice → refs) | ✅ working, validated live |
| Existence & status probes (`ExistsTransaction`/`GetTransactionStatus`) | ✅ working, validated live |
| Read entities + contacts (`GetEntities`/`GetEntitiesOfType`/`GetEntityContacts`) | ✅ working, validated live |
| Typed `Entity` / `EntityContact` read models + XML parser | ✅ working |
| Read catalogs (currencies, accounts, charges, events, ports) | ✅ working, validated live |
| Typed catalog read models + XML parser | ✅ working |
| Read rates (standard / client / carrier) | ✅ working, validated live |
| Typed `Rate` read model + XML parser | ✅ working |
| Read attachments + documents (`GetAllAttachments`/`GetAttachment`/`GetWebDocument`) | ✅ working, validated live |
| Typed attachment / document read models + XML parser | ✅ working |
| Read warehouse inventory (item definitions + items on hand) | ✅ working, validated live |
| Typed `ItemDefinition` / `InventoryItem` read models + XML parser | ✅ working |
| Unpaginated batch reads (`GetTransRangeByDate`, by billing client) | ✅ working, validated live |
| Server-side JavaScript filtering on the reads that accept it | ⚠️ implemented; no filter function defined in the install to validate a match |
| CLI (`magaya shipments`, `magaya entities`) | ✅ working |
| Vehicle lookup by VIN (`GetItemFromVIN`) | ⚠️ implemented; only the not-found path is validated (no vehicles on hand) |
| LiveTrack client reads (`GetSecureTrackingTransaction`) | ⚠️ implemented; only the access-denied path is validated (no LiveTrack credentials) |
| Proof of delivery (`GetPODData`) | ⏳ not yet — no POD data on hand to model against |
| **Create / update** transactions (`SetTransaction`) | 🚫 out of scope for now |

---

## API coverage

Progress toward consuming the full Magaya API. Read methods are the current
focus; write methods are out of scope for now. Keep this section current with
the `update-api-coverage` skill whenever a method is finished.

Legend: ✅ done · 🟡 read, pending · 🚫 write, out of scope · 🔧 generic

<!-- API-COVERAGE:START -->
| Metric | Count |
| --- | --- |
| Total API methods | 59 |
| ✅ Done | 30 |
| 🟡 Read, pending | 6 |
| 🚫 Write (out of scope) | 22 |
| 🔧 Generic (`Invoke`) | 1 |

**Read coverage: 28 / 34 read methods (~82%).**

### Session
| Method | Status |
| --- | --- |
| StartSession | ✅ |
| EndSession | ✅ |

### Generic transactions
| Method | Status |
| --- | --- |
| GetFirstTransbyDate | ✅ |
| GetNextTransbyDate | ✅ |
| GetTransaction | ✅ |
| GetTransRangeByDate | ✅ |
| GetTransRangeByDateJS | 🟡 |
| GetFirstTransbyDateJS | 🟡 |
| ExistsTransaction | ✅ |
| GetTransactionStatus | ✅ |
| GetTransactionsByBillingClient | ✅ |
| GetRelatedTransactions | ✅ |
| GetAccountingTransactions | ✅ |
| GetEntityTransactions | ✅ |
| SetTransaction | 🚫 |
| DeleteTransaction | 🚫 |
| RenameTransaction | 🚫 |
| SetTransactionEvents | 🚫 |
| SetTransactionCharges | 🚫 |

### Entities
| Method | Status |
| --- | --- |
| GetEntities | ✅ |
| GetEntitiesOfType | ✅ |
| GetEntityContacts | ✅ |
| SetEntity | 🚫 |
| SetParentEntity | 🚫 |

### Rates
| Method | Status |
| --- | --- |
| GetStandardRates | ✅ |
| GetClientRates | ✅ |
| GetCarrierRates | ✅ |
| SetRate | 🚫 |

### Attachments
| Method | Status |
| --- | --- |
| GetAllAttachments | ✅ |
| GetAttachment | ✅ |
| SetAttachment | 🚫 |

### Transaction log
| Method | Status |
| --- | --- |
| QueryLog | ✅ |
| QueryLogJS | 🟡 |

### Online / purchase / sales orders
| Method | Status |
| --- | --- |
| SubmitSalesOrder | 🚫 |
| SubmitCargoRelease | 🚫 |
| SubmitShipment | 🚫 |
| SubmitPickupOrder | 🚫 |
| UpdateOrder | 🚫 |
| ValidateSalesOrder | 🚫 |
| CancelSalesOrder | 🚫 |
| ApproveOrder | 🚫 |

### Miscellaneous
| Method | Status |
| --- | --- |
| GetAccountDefinitions | ✅ |
| GetChargeDefinitions | ✅ |
| GetClientChargeDefinitions | ✅ |
| GetActiveCurrencies | ✅ |
| GetEventDefinitions | ✅ |
| GetWorkingPorts | ✅ |
| GetItemFromVIN | 🟡 |
| GetItemDefinitionsByCustomer | ✅ |
| GetInventoryItemsByItemDefinition | ✅ |
| GetWebDocument | ✅ |
| GetSecureTrackingTransaction | 🟡 |
| GetPODData | 🟡 |
| SetShipmentStatus | 🚫 |
| SetApprovalStatus | 🚫 |
| SetCustomFieldValue | 🚫 |
| SetTrackingUser | 🚫 |
| UpdatePOD | 🚫 |
| Invoke | 🔧 |
<!-- API-COVERAGE:END -->

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

**Where `.env` is looked for.** Not just the current directory — the CLI is
meant to run from wherever you happen to be. It is searched the way `git` looks
for a repository, first hit winning:

1. `MAGAYA_ENV_FILE`, if set. An explicit path stops the search, so a typo fails
   loudly instead of quietly loading a different file.
2. `.env` in the current directory, then each parent up to `/`. This is what
   makes `magaya` work from any subdirectory of your project.
3. `.env` under `$XDG_CONFIG_HOME/magaya-toolkit` (or
   `~/.config/magaya-toolkit`) — put it there to use the CLI from anywhere.

Real environment variables always win over the file, so
`MAGAYA_API_URL=… magaya shipments …` overrides a `.env` without editing it. When
nothing is found, the CLI says which paths it tried.

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

# List entities as a table (Name, Kind, EntityID, Email, Phone)
uv run magaya entities

# Customers whose name starts with "MUE", as JSON
uv run magaya entities MUE --type client --json
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

`magaya entities` options:

| Option | Default | Meaning |
| --- | --- | --- |
| `START_WITH` (positional) | *(none)* | Filter entities by name prefix. |
| `--type` | *(all)* | `client`, `carrier`, `vendor`, `forwarding-agent`, `warehouse-provider`, `employee`, `salesman`, `division` (`customer` = alias of `client`). |
| `--json` | off | Emit a JSON array instead of the table. |

## Architecture (hexagonal)

```
src/magaya_toolkit/
├── __init__.py        # public SDK surface (Magaya, MagayaSettings, Shipment, Entity, errors…)
├── facade.py          # Magaya — SDK front door; owns one managed session
├── resources.py       # ShipmentsResource, EntitiesResource — typed reads over the session
├── domain/            # pure models + errors (no SOAP, no XML libs)
│   ├── common.py      #   shared read models (Measure, Address)
│   ├── shipment.py    #   Shipment read model
│   ├── entity.py      #   Entity, EntityContact, EntityType read models
│   └── errors.py      #   MagayaError, ApiError, XmlValidationError, SessionError
├── application/       # ports (Protocols) + use cases — the boundaries
│   ├── ports.py       #   MagayaReader, ShipmentParser, EntityParser
│   └── use_cases.py   #   list_shipments(...), collect_shipments(...)
└── infrastructure/    # adapters that implement the ports
    ├── config.py      #   MagayaSettings (.env)
    ├── soap/          #   MagayaSoapClient (httpx, hand-built SOAP 1.1)
    └── xml/           #   LxmlShipmentParser, LxmlEntityParser
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
  by every subsequent call. That key is a **constant of the credential**, not a
  per-session token — verified against a production capture (16 consecutive
  `StartSession` calls, same key every time; 180 calls/hour, zero failures). A
  second `StartSession` revalidates the same key rather than replacing it, and
  `EndSession(access_key)` from any process kills the one session shared by
  every process using that credential (e.g. a production ETL), not just the
  caller's. Because of this, the toolkit does NOT call `EndSession` by default
  — it is opt-in via `end_session_on_close=True`. Only one session per key/IP
  is allowed (`too_many_open_sessions` otherwise).
- **Reading by date.** `GetFirstTransbyDate` returns a **cookie** cursor (not the
  data). `GetNextTransbyDate(cookie)` returns the transaction XML **and an
  updated cookie** — you must thread that updated cookie into the next call, or
  you re-fetch the same page forever. Iterate until `more_results == 0`.
- **Reading entities.** `GetEntities`, `GetEntitiesOfType`, and
  `GetEntityContacts` are **single-call** reads (no pagination cookie): each
  returns one XML blob (`entity_list_xml` / `contact_list_xml`). The child tag of
  `<Entities>` (`Client`, `Carrier`, `Vendor`, …) is the entity kind.
- **XML namespace.** Returned transactions are namespaced under
  `http://www.magaya.com/XMLSchema/V1`.
- **Best practices** (from the Magaya API docs): one API user per integration;
  no parallel calls; exponential backoff on `Timeout`; prefer
  `GetFirst`/`GetNextTransbyDate` over large single-shot date ranges.

Full reference (login required): <https://dev.magaya.com/index.php/API>.
```
