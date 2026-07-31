# magaya-toolkit — Claude Code project context

Read-only, typed Python **SDK over the Magaya SOAP API**. Entry point: the
`Magaya` facade (`facade.py`) → typed models, never raw SOAP/XML.

Conventions and the coverage skill: @AGENTS.md
Full usage, architecture, and the API coverage catalog live in `README.md`.

## Commands

- `uv sync` — install deps from the lockfile
- `uv run pytest -q` — tests (network-free; they use `httpx.MockTransport` — never hit the real API)
- `uv run ruff check`
- `uv run magaya shipments --from 2025-01-01 --to 2025-01-31`
- `uv run magaya entities MUE --type customer`

## Credentials

Connection config lives in `.env` (gitignored): `MAGAYA_API_URL`,
`MAGAYA_USERNAME`, `MAGAYA_PASSWORD`. Never commit `.env` or print its contents.

## Magaya API facts (hard-won — do not rediscover)

- Transport: SOAP 1.1 over HTTPS `POST`, `Content-Type: text/xml`, method
  namespace `urn:CSSoapService`, no WSDL, no `SOAPAction`. Cloud endpoint shape:
  `https://<COMPANY_ID>.magayacloud.com/api/Invoke?Handler=CSSoapService`.
- Session: `StartSession(user, pass) -> int access_key`; always `EndSession`. The
  facade owns ONE session per `with Magaya(...)` block — reuse it, never reopen
  per call.
- Date-range reads: `GetFirstTransbyDate` returns a **cookie** (no data);
  `GetNextTransbyDate(cookie)` returns data **plus an updated cookie you MUST
  thread into the next call** — reusing the old cookie loops over the same page
  forever. Iterate until `more_results == 0`.
- `backwards_order` MUST be sent as `xsd:int` (0/1); `xsd:boolean` is rejected
  ("SOAP Invalid Request").
- Entity reads are single-call (no pagination cookie). Response data namespace:
  `http://www.magaya.com/XMLSchema/V1`.
- Full method reference (login required): https://dev.magaya.com/index.php/API

## Adding a read method

Client call → typed model/parser → facade resource or use case → network-free
test. Then run the `update-api-coverage` skill to refresh the coverage catalog
in `README.md`.

## Memory

This project uses Engram persistent memory. Run `mem_context` / `mem_search` at
session start for prior decisions and the full set of validated API details.
