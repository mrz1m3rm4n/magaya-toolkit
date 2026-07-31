# AGENTS.md

Guidance for AI agents working in this repository.

## Project

`magaya-toolkit` — a read-only, typed Python SDK over the Magaya SOAP API.
Hexagonal layout: `domain` ← `application` (ports + use cases) ← `infrastructure`
(SOAP client, XML parsers). The `Magaya` facade is the public entry point.

## Conventions

- Scope is read-only. Do not add write/create operations (`Set*`, `Submit*`,
  `Delete*`, …) unless the scope is explicitly reopened.
- Every new read method needs: a client call, a typed model/parser, a facade
  resource or use case, and a network-free test (`httpx.MockTransport`).
- Keep credentials out of the repo — `.env` is gitignored.

## Skills

- **update-api-coverage** (`.claude/skills/update-api-coverage/SKILL.md`) — run
  whenever a Magaya API method is finished, to update the `## API coverage`
  catalog in `README.md` and recompute its tallies.
